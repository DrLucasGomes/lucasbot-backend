import os

import requests
from fastapi import APIRouter, BackgroundTasks, Request

from main import STATUS_PAGOS, URL, obter_headers_supabase, webhook_kiwify


router = APIRouter(tags=["kiwify-pix-recovery"])

PIX_TABLE = "recovery_pix_orders"
KIT_BASE_URL = "https://api.convertkit.com/v3"


def _ordem(dados):
    ordem = dados.get("order") or dados.get("Order") or {}
    return ordem if isinstance(ordem, dict) else {}


def _texto(valor):
    return str(valor or "").strip()


def _evento_pix_criado(dados) -> bool:
    ordem = _ordem(dados)
    return (
        _texto(ordem.get("webhook_event_type")).lower() == "pix_created"
        and _texto(ordem.get("payment_method")).lower() == "pix"
        and _texto(ordem.get("order_status")).lower() == "waiting_payment"
        and bool(_texto(ordem.get("order_id")))
    )


def _evento_pago(dados) -> bool:
    ordem = _ordem(dados)
    return _texto(ordem.get("order_status")).lower() in STATUS_PAGOS


def _dados_pix(dados):
    ordem = _ordem(dados)
    cliente = ordem.get("Customer") or ordem.get("customer") or {}
    if not isinstance(cliente, dict):
        cliente = {}

    return {
        "order_id": _texto(ordem.get("order_id")),
        "order_ref": _texto(ordem.get("order_ref")) or None,
        "email": _texto(cliente.get("email") or cliente.get("Email")),
    }


def _registro_retornado(resposta) -> bool:
    if resposta.status_code not in (200, 201):
        return False
    try:
        dados = resposta.json()
    except Exception:
        return False
    return isinstance(dados, list) and bool(dados)


def adquirir_processamento(order_id: str, order_ref: str | None, email: str) -> bool:
    headers = obter_headers_supabase(prefer="return=representation")
    resposta = requests.post(
        f"{URL}/rest/v1/{PIX_TABLE}",
        json={
            "order_id": order_id,
            "order_ref": order_ref,
            "email": email,
            "status": "processing",
        },
        headers=headers,
        timeout=3,
    )
    if _registro_retornado(resposta):
        return True

    if resposta.status_code == 409:
        retry = requests.patch(
            f"{URL}/rest/v1/{PIX_TABLE}",
            params={"order_id": f"eq.{order_id}", "status": "eq.failed"},
            json={"status": "processing", "email": email},
            headers=headers,
            timeout=3,
        )
        return _registro_retornado(retry)

    return False


def atualizar_status(order_id: str, status: str) -> bool:
    resposta = requests.patch(
        f"{URL}/rest/v1/{PIX_TABLE}",
        params={"order_id": f"eq.{order_id}"},
        json={"status": status},
        headers=obter_headers_supabase(prefer="return=representation"),
        timeout=3,
    )
    return _registro_retornado(resposta)


def _alterar_tag_kit(email: str, acao: str) -> bool:
    api_key = os.getenv("CONVERTKIT_API_KEY")
    tag_id = os.getenv("TAG_PIX_ID")
    if not api_key or not tag_id or not email:
        return False

    resposta = requests.post(
        f"{KIT_BASE_URL}/tags/{tag_id}/{acao}",
        json={"api_key": api_key, "email": email},
        timeout=5,
    )
    return resposta.status_code in (200, 201, 204)


def processar_pix_criado(dados):
    info = _dados_pix(dados)
    order_id = info["order_id"]
    email = info["email"]
    if not order_id or not email:
        return

    try:
        if not adquirir_processamento(order_id, info["order_ref"], email):
            return

        sucesso = _alterar_tag_kit(email, "subscribe")
        atualizar_status(order_id, "completed" if sucesso else "failed")
    except Exception as exc:
        print(f"[PIX Recovery] Falha ao iniciar recovery: {str(exc)}")
        try:
            atualizar_status(order_id, "failed")
        except Exception:
            pass


def cancelar_pix_por_pagamento(dados):
    info = _dados_pix(dados)
    order_id = info["order_id"]
    email = info["email"]
    if not email:
        return

    try:
        removido = _alterar_tag_kit(email, "unsubscribe")
        if order_id and removido:
            atualizar_status(order_id, "cancelled")
    except Exception as exc:
        print(f"[PIX Recovery] Falha ao cancelar recovery: {str(exc)}")


@router.post("/kiwify")
async def webhook_kiwify_com_pix(request: Request, background_tasks: BackgroundTasks):
    dados = await request.json()

    # Preserva integralmente o comportamento existente de /kiwify.
    resposta = await webhook_kiwify(request, background_tasks)

    # PIX e pagamento sao efeitos adicionais, isolados do fluxo principal.
    if _evento_pix_criado(dados):
        background_tasks.add_task(processar_pix_criado, dados)
    elif _evento_pago(dados):
        background_tasks.add_task(cancelar_pix_por_pagamento, dados)

    return resposta
