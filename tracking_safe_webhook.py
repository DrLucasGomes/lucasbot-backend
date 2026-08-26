"""Webhook /webhook protegido para o ambiente Lucas Tracking.

Mantem o comportamento atual do backend, mas aplica regra de first-touch:
se um lead ja possui origem/campanha, uma chamada posterior do ManyChat nao
pode sobrescrever esses campos (ex.: WhatsApp Direto / Fallback_Entrada).
"""

import requests
from fastapi import APIRouter, BackgroundTasks, Request
from starlette.concurrency import run_in_threadpool

import main
from kit_utils import primeiro_nome

router = APIRouter()


async def diagnosticar_background_kit(email_lead, first_name):
    print("stage=kit_background_callable_entered", flush=True)
    try:
        print("stage=kit_threadpool_dispatch_started", flush=True)
        await run_in_threadpool(
            main.adicionar_lead_convertkit, email_lead, first_name
        )
        print(
            "stage=kit_threadpool_dispatch_completed success=True",
            flush=True,
        )
    except Exception:
        print(
            "stage=kit_threadpool_dispatch_completed success=False",
            flush=True,
        )
        raise


def buscar_atribuicao_existente(manychat_id: str) -> dict:
    r = requests.get(
        f"{main.URL}/rest/v1/leads_vigor",
        params={
            "manychat_id": f"eq.{manychat_id}",
            "select": "origem,campanha",
            "limit": "1",
        },
        headers=main.obter_headers_supabase(),
        timeout=15,
    )
    if r.status_code != 200:
        return {}
    dados = r.json()
    return dados[0] if isinstance(dados, list) and dados else {}


def preservar_first_touch(dados_limpos: dict, existente: dict) -> dict:
    protegido = dict(dados_limpos)

    origem_existente = existente.get("origem")
    campanha_existente = existente.get("campanha")

    if main.valor_valido(origem_existente):
        protegido["origem"] = str(origem_existente).strip()
    if main.valor_valido(campanha_existente):
        protegido["campanha"] = str(campanha_existente).strip()

    return protegido


@router.post("/webhook")
async def webhook_protegido(request: Request, background_tasks: BackgroundTasks):
    print("stage=manychat_wrapper_entered")
    try:
        dados_brutos = await request.json()
        name_field_detected = (
            isinstance(dados_brutos, dict)
            and "nome" in dados_brutos
            and main.valor_valido(dados_brutos.get("nome"))
        )
        print(f"stage=name_field_detected value={name_field_detected}")
        mc_id = dados_brutos.get("manychat_id")

        if not main.manychat_id_valido(mc_id):
            return {"status": "erro", "detalhe": "manychat_id nao encontrado"}

        mc_id = str(mc_id).strip()
        dados_limpos = main.limpar_payload_supabase(dados_brutos)
        dados_limpos["manychat_id"] = mc_id

        # Regra critica: a origem de aquisicao e first-touch. Fallback e
        # retomadas podem completar outros campos, mas nao reescrever a origem.
        existente = buscar_atribuicao_existente(mc_id)
        dados_limpos = preservar_first_touch(dados_limpos, existente)

        headers_supabase = main.obter_headers_supabase(
            prefer="resolution=merge-duplicates,return=representation"
        )
        response = requests.post(
            f"{main.URL}/rest/v1/leads_vigor?on_conflict=manychat_id",
            json=dados_limpos,
            headers=headers_supabase,
            timeout=15,
        )

        sucesso = response.status_code in (200, 201, 204)
        email_lead = dados_limpos.get("email")
        first_name = primeiro_nome(dados_limpos.get("nome"))
        print(f"stage=first_name_normalized value={bool(first_name)}")

        if sucesso and main.valor_valido(email_lead):
            print(
                "stage=kit_task_scheduled "
                f"first_name_present={bool(first_name)}"
            )
            background_tasks.add_task(
                diagnosticar_background_kit, email_lead, first_name
            )

        return {
            "status": "sucesso" if sucesso else "erro_supabase",
            "code": response.status_code,
            "payload_enviado": dados_limpos,
            "origem_preservada": bool(main.valor_valido(existente.get("origem"))),
            "campanha_preservada": bool(main.valor_valido(existente.get("campanha"))),
            "convertkit_lead_agendado": bool(sucesso and main.valor_valido(email_lead)),
            "resposta_supabase": main.resposta_segura(response),
        }

    except Exception as exc:
        return {"status": "erro_critico", "detalhe": str(exc)}
