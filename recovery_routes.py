import os
import re
from datetime import datetime, timedelta, timezone

import requests
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, field_validator

from main import STATUS_PAGOS, URL, obter_headers_supabase


router = APIRouter(prefix="/recovery", tags=["recovery"])

RECOVERY_TABLE = "recovery_video_plays"
KIT_BASE_URL = "https://api.convertkit.com/v3"
RESPOSTA_GENERICA = {"status": "processado"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SRC_RE = re.compile(r"^mc_([0-9]+)$")
PROCESSING_STALE_MINUTES = 5


class VideoPlayPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    src: str

    @field_validator("src")
    @classmethod
    def validar_src(cls, valor: str) -> str:
        texto = str(valor).strip()
        if not SRC_RE.fullmatch(texto):
            raise ValueError("src invalido")
        return texto


def extrair_manychat_id(payload: VideoPlayPayload) -> str:
    return SRC_RE.fullmatch(payload.src).group(1)


def email_valido(email) -> bool:
    if not isinstance(email, str):
        return False
    return bool(EMAIL_RE.fullmatch(email.strip()))


def buscar_lead_por_manychat_id(manychat_id: str):
    resposta = requests.get(
        f"{URL}/rest/v1/leads_vigor",
        params={
            "manychat_id": f"eq.{manychat_id}",
            "select": "id,email,manychat_id,status_pagamento",
            "limit": "1",
        },
        headers=obter_headers_supabase(),
        timeout=3,
    )
    if resposta.status_code != 200:
        return None

    dados = resposta.json()
    if isinstance(dados, list) and dados:
        return dados[0]
    return None


def _registro_retornado(resposta) -> bool:
    if resposta.status_code not in (200, 201):
        return False
    try:
        dados = resposta.json()
    except Exception:
        return False
    return isinstance(dados, list) and bool(dados)


def adquirir_processamento(manychat_id: str) -> bool:
    """Adquire uma tentativa nova ou retoma atomicamente uma tentativa failed."""
    headers = obter_headers_supabase(prefer="return=representation")
    resposta = requests.post(
        f"{URL}/rest/v1/{RECOVERY_TABLE}",
        json={"manychat_id": manychat_id, "status": "processing"},
        headers=headers,
        timeout=3,
    )
    if _registro_retornado(resposta):
        return True

    # A chave unica ja existe. Somente failed pode voltar a processing; o filtro
    # torna a aquisicao segura quando dois retries chegam ao mesmo tempo.
    if resposta.status_code == 409:
        retry = requests.patch(
            f"{URL}/rest/v1/{RECOVERY_TABLE}",
            params={"manychat_id": f"eq.{manychat_id}", "status": "eq.failed"},
            json={"status": "processing"},
            headers=headers,
            timeout=3,
        )
        if _registro_retornado(retry):
            return True

        limite_stale = datetime.now(timezone.utc) - timedelta(
            minutes=PROCESSING_STALE_MINUTES
        )
        retry_stale = requests.patch(
            f"{URL}/rest/v1/{RECOVERY_TABLE}",
            params={
                "manychat_id": f"eq.{manychat_id}",
                "status": "eq.processing",
                "updated_at": f"lt.{limite_stale.isoformat()}",
            },
            json={"status": "processing"},
            headers=headers,
            timeout=3,
        )
        return _registro_retornado(retry_stale)

    return False


def atualizar_processamento(manychat_id: str, status: str) -> bool:
    resposta = requests.patch(
        f"{URL}/rest/v1/{RECOVERY_TABLE}",
        params={"manychat_id": f"eq.{manychat_id}", "status": "eq.processing"},
        json={"status": status},
        headers=obter_headers_supabase(prefer="return=representation"),
        timeout=3,
    )
    return _registro_retornado(resposta)


def aplicar_tag_recuperacao(email: str) -> bool:
    api_key = os.getenv("CONVERTKIT_API_KEY")
    tag_id = os.getenv("TAG_RECUPERACAO_VIDEO_ID")
    if not api_key or not tag_id:
        return False

    resposta = requests.post(
        f"{KIT_BASE_URL}/tags/{tag_id}/subscribe",
        json={"api_key": api_key, "email": email},
        timeout=5,
    )
    return resposta.status_code in (200, 201, 204)


@router.post("/video-play")
def video_play(payload: VideoPlayPayload):
    manychat_id = extrair_manychat_id(payload)

    try:
        lead = buscar_lead_por_manychat_id(manychat_id)
        if not lead:
            return RESPOSTA_GENERICA

        email = lead.get("email")
        status = str(lead.get("status_pagamento") or "").strip().lower()
        if not email_valido(email) or status in STATUS_PAGOS:
            return RESPOSTA_GENERICA

        if not adquirir_processamento(manychat_id):
            return RESPOSTA_GENERICA

        try:
            sucesso = aplicar_tag_recuperacao(email.strip())
        except Exception as exc:
            print(f"[Recovery Video Play] Falha ao aplicar tag no Kit: {str(exc)}")
            sucesso = False

        destino = "completed" if sucesso else "failed"
        try:
            atualizar_processamento(manychat_id, destino)
        except Exception as exc:
            print(f"[Recovery Video Play] Falha ao atualizar estado {destino}: {str(exc)}")

        return RESPOSTA_GENERICA
    except Exception as exc:
        print(f"[Recovery Video Play] Falha operacional: {str(exc)}")
        return RESPOSTA_GENERICA
