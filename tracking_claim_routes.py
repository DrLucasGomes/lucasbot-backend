from datetime import datetime, timedelta, timezone

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tracking_origin import (
    INFERENCE_WINDOW_SECONDS,
    claim_exato,
    claim_inferido,
    extrair_token_mensagem,
)
from tracking_routes import SUPABASE_URL, headers_supabase


router = APIRouter()


class ClaimPayload(BaseModel):
    manychat_id: str
    message: str | None = None


def buscar_click_por_token(token: str):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/click_sessions",
        params={
            "token": f"eq.{token}",
            "claimed": "eq.false",
            "select": "*",
            "limit": "1",
        },
        headers=headers_supabase(),
        timeout=10,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Supabase {r.status_code}: {r.text[:1000]}")
    dados = r.json()
    return dados[0] if isinstance(dados, list) and dados else None


def buscar_clicks_recentes():
    agora = datetime.now(timezone.utc)
    inicio = agora - timedelta(seconds=INFERENCE_WINDOW_SECONDS)
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/click_sessions",
        params={
            "claimed": "eq.false",
            "created_at": f"gte.{inicio.isoformat()}",
            "expires_at": f"gt.{agora.isoformat()}",
            "select": "*",
            "order": "created_at.desc",
            "limit": "10",
        },
        headers=headers_supabase(),
        timeout=10,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Supabase {r.status_code}: {r.text[:1000]}")
    dados = r.json()
    return dados if isinstance(dados, list) else []


def escolher_candidato_inferido(clicks: list[dict]):
    """
    So infere quando nao ha risco de atribuir a campanha errada.

    1 clique recente -> candidato unico (medium).
    2+ cliques recentes -> so aceita se TODOS apontarem para a mesma
    origem/campanha/video; nesse caso a identidade da sessao pode ser ambigua,
    mas a atribuicao de campanha continua consistente (high para campanha).
    """
    if not clicks:
        return None, None, None

    if len(clicks) == 1:
        return clicks[0], "recent_unique_click", "medium"

    assinaturas = {
        (
            str(c.get("origem") or "").strip().lower(),
            str(c.get("campanha") or "").strip().lower(),
            str(c.get("video") or "").strip().lower(),
        )
        for c in clicks
    }

    if len(assinaturas) == 1:
        # Usa o mais recente apenas como sessao representativa; o que estamos
        # afirmando com confianca e a campanha, nao a identidade exata do clique.
        return clicks[0], "recent_campaign_consensus", "high"

    return None, None, None


def salvar_claim(registro: dict):
    token = registro["token"]
    payload = {
        "manychat_id": registro.get("manychat_id"),
        "claimed": True,
        "claim_method": registro.get("claim_method"),
        "claim_confidence": registro.get("claim_confidence"),
        "claimed_at": registro.get("claimed_at"),
    }
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/click_sessions",
        params={"token": f"eq.{token}", "claimed": "eq.false"},
        json=payload,
        headers=headers_supabase(),
        timeout=10,
    )
    if r.status_code not in (200, 204):
        raise HTTPException(status_code=502, detail=f"Supabase {r.status_code}: {r.text[:1000]}")


def garantir_origem_no_lead(registro: dict, manychat_id: str):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/leads_vigor",
        params={
            "manychat_id": f"eq.{manychat_id}",
            "select": "id,manychat_id,origem,campanha",
            "limit": "1",
        },
        headers=headers_supabase(),
        timeout=10,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Supabase lead GET {r.status_code}: {r.text[:1000]}")

    leads = r.json() if isinstance(r.json(), list) else []
    origem = registro.get("origem")
    campanha = registro.get("campanha")

    if leads:
        lead = leads[0]
        patch = {}
        if not lead.get("origem") and origem:
            patch["origem"] = origem
        if not lead.get("campanha") and campanha:
            patch["campanha"] = campanha
        if patch:
            p = requests.patch(
                f"{SUPABASE_URL}/rest/v1/leads_vigor",
                params={"id": f"eq.{lead['id']}"},
                json=patch,
                headers=headers_supabase(),
                timeout=10,
            )
            if p.status_code not in (200, 204):
                raise HTTPException(status_code=502, detail=f"Supabase lead PATCH {p.status_code}: {p.text[:1000]}")
        return "preservado_ou_preenchido"

    payload = {"manychat_id": str(manychat_id)}
    if origem:
        payload["origem"] = origem
    if campanha:
        payload["campanha"] = campanha

    p = requests.post(
        f"{SUPABASE_URL}/rest/v1/leads_vigor?on_conflict=manychat_id",
        json=payload,
        headers={**headers_supabase(), "Prefer": "resolution=merge-duplicates,return=representation"},
        timeout=10,
    )
    if p.status_code not in (200, 201, 204):
        raise HTTPException(status_code=502, detail=f"Supabase lead UPSERT {p.status_code}: {p.text[:1000]}")
    return "lead_esqueleto_criado"


@router.post("/tracking/claim")
def claim_tracking(payload: ClaimPayload):
    manychat_id = str(payload.manychat_id or "").strip()
    if not manychat_id:
        raise HTTPException(status_code=400, detail="manychat_id obrigatorio")

    token = extrair_token_mensagem(payload.message)
    registro = None
    metodo = None

    if token:
        registro = buscar_click_por_token(token)
        if registro:
            agora = datetime.now(timezone.utc)
            exp = datetime.fromisoformat(str(registro["expires_at"]).replace("Z", "+00:00"))
            if agora >= exp:
                registro = None
            else:
                registro = claim_exato(registro, manychat_id=manychat_id, agora=agora)
                metodo = "token"

    if not registro:
        clicks = buscar_clicks_recentes()
        candidato, metodo_inferido, confianca = escolher_candidato_inferido(clicks)
        if candidato:
            registro = claim_inferido(
                candidato,
                manychat_id=manychat_id,
                metodo=metodo_inferido,
                confianca=confianca,
            )
            metodo = metodo_inferido

    if not registro:
        return {
            "status": "sem_atribuicao_segura",
            "manychat_id": manychat_id,
            "motivo": "token ausente/invalido e cliques recentes apontam para campanhas diferentes ou nao existem",
        }

    salvar_claim(registro)
    acao_lead = garantir_origem_no_lead(registro, manychat_id)

    return {
        "status": "claimed",
        "manychat_id": manychat_id,
        "origem": registro.get("origem"),
        "campanha": registro.get("campanha"),
        "video": registro.get("video"),
        "claim_method": registro.get("claim_method"),
        "claim_confidence": registro.get("claim_confidence"),
        "metodo_detectado": metodo,
        "acao_lead": acao_lead,
    }
