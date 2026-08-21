import os
import threading
import time
from urllib.parse import quote
from uuid import uuid4

import requests
from fastapi import APIRouter, BackgroundTasks, Request

from main import STATUS_PAGOS, URL, obter_headers_supabase, webhook_kiwify


router = APIRouter(tags=["kiwify-pix-recovery"])

PIX_TABLE = "recovery_pix_orders"
KIT_BASE_URL = "https://api.convertkit.com/v3"
PROCESSING_STALE_MINUTES = 5
KIWIFY_API_BASE_URL = "https://public-api.kiwify.com/v1"
KIWIFY_PENDING_STATUSES = frozenset({"pending", "waiting_payment"})
KIWIFY_API_TIMEOUT_SECONDS = 5

_kiwify_oauth_lock = threading.Lock()
_kiwify_oauth_cache = {"access_token": "", "expires_at": 0.0}


def _ordem(dados):
    if not isinstance(dados, dict):
        return {}

    ordem = dados.get("order") or dados.get("Order")
    if isinstance(ordem, dict):
        return ordem

    # A Kiwify pode entregar/reentregar os campos da ordem diretamente na raiz.
    if any(
        chave in dados
        for chave in ("order_id", "order_status", "payment_method", "webhook_event_type")
    ):
        return dados

    return {}


def _texto(valor):
    return str(valor or "").strip()


def _obter_oauth_token_kiwify() -> str:
    """Obtém e reutiliza o OAuth da Kiwify sem expor credenciais."""
    agora = time.monotonic()
    token_cache = _texto(_kiwify_oauth_cache.get("access_token"))
    if token_cache and agora < float(_kiwify_oauth_cache.get("expires_at") or 0):
        return token_cache

    client_id = _texto(os.getenv("KIWIFY_API_CLIENT_ID"))
    client_secret = _texto(os.getenv("KIWIFY_API_CLIENT_SECRET"))
    if not client_id or not client_secret:
        return ""

    with _kiwify_oauth_lock:
        agora = time.monotonic()
        token_cache = _texto(_kiwify_oauth_cache.get("access_token"))
        if token_cache and agora < float(_kiwify_oauth_cache.get("expires_at") or 0):
            return token_cache

        try:
            resposta = requests.post(
                f"{KIWIFY_API_BASE_URL}/oauth/token",
                data={"client_id": client_id, "client_secret": client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=KIWIFY_API_TIMEOUT_SECONDS,
            )
        except Exception:
            return ""

        if resposta.status_code != 200:
            return ""

        try:
            corpo = resposta.json()
        except Exception:
            return ""
        if not isinstance(corpo, dict):
            return ""

        access_token = _texto(corpo.get("access_token"))
        try:
            expires_in = max(int(corpo.get("expires_in") or 0), 0)
        except (TypeError, ValueError):
            return ""
        if not access_token or expires_in <= 0:
            return ""

        # Renova com margem para nunca usar token no limite da expiração.
        ttl_cache = max(expires_in - 60, 1)
        _kiwify_oauth_cache["access_token"] = access_token
        _kiwify_oauth_cache["expires_at"] = time.monotonic() + ttl_cache
        return access_token


def confirmar_venda_kiwify(
    order_id: str,
    statuses_aceitos,
    payment_method_esperado: str | None = None,
) -> dict:
    """Retorna somente dados mínimos de uma venda confirmada; falhas fecham o fluxo."""
    order_id = _texto(order_id)
    account_id = _texto(os.getenv("KIWIFY_ACCOUNT_ID"))
    access_token = _obter_oauth_token_kiwify()
    if not order_id or not account_id or not access_token:
        return {}

    try:
        resposta = requests.get(
            f"{KIWIFY_API_BASE_URL}/sales/{quote(order_id, safe='')}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "x-kiwify-account-id": account_id,
            },
            timeout=KIWIFY_API_TIMEOUT_SECONDS,
        )
    except Exception:
        return {}

    if resposta.status_code != 200:
        return {}

    try:
        venda = resposta.json()
    except Exception:
        return {}
    if not isinstance(venda, dict) or _texto(venda.get("id")) != order_id:
        return {}

    status = _texto(venda.get("status")).lower()
    statuses_normalizados = {_texto(item).lower() for item in statuses_aceitos}
    if status not in statuses_normalizados:
        return {}

    payment_method = _texto(venda.get("payment_method")).lower()
    if payment_method_esperado and payment_method != _texto(payment_method_esperado).lower():
        return {}

    customer = venda.get("customer")
    if not isinstance(customer, dict):
        customer = {}

    return {
        "id": order_id,
        "status": status,
        "payment_method": payment_method,
        "email": _texto(customer.get("email")),
    }


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
        "email": _texto(cliente.get("email") or cliente.get("Email")),
    }


def _rpc_bool(nome: str, payload: dict) -> bool:
    resposta = requests.post(
        f"{URL}/rest/v1/rpc/{nome}",
        json=payload,
        headers=obter_headers_supabase(),
        timeout=3,
    )
    if resposta.status_code != 200:
        return False
    try:
        return resposta.json() is True
    except Exception:
        return False


def adquirir_processamento(order_id: str, email: str, attempt_token: str) -> bool:
    return _rpc_bool(
        "recovery_pix_acquire",
        {
            "p_order_id": order_id,
            "p_email": email,
            "p_attempt_token": attempt_token,
            "p_stale_minutes": PROCESSING_STALE_MINUTES,
        },
    )


def transicionar(order_id: str, attempt_token: str, origem: str, destino: str) -> bool:
    return _rpc_bool(
        "recovery_pix_transition",
        {
            "p_order_id": order_id,
            "p_attempt_token": attempt_token,
            "p_from_status": origem,
            "p_to_status": destino,
        },
    )


def persistir_cancelamento(order_id: str, email: str | None) -> bool:
    return _rpc_bool(
        "recovery_pix_cancel",
        {"p_order_id": order_id, "p_email": email or None},
    )


def reabrir_cancelamento(order_id: str, attempt_token: str) -> bool:
    return _rpc_bool(
        "recovery_pix_reopen_cancel",
        {"p_order_id": order_id, "p_attempt_token": attempt_token},
    )


def confirmar_cancelamento(order_id: str) -> bool:
    return _rpc_bool(
        "recovery_pix_confirm_cancel",
        {"p_order_id": order_id},
    )


def buscar_ledger(order_id: str) -> dict:
    if not order_id:
        return {}

    resposta = requests.get(
        f"{URL}/rest/v1/{PIX_TABLE}",
        params={
            "order_id": f"eq.{order_id}",
            "select": "email,status,attempt_token,subscribe_attempted",
            "limit": "1",
        },
        headers=obter_headers_supabase(),
        timeout=3,
    )
    if resposta.status_code != 200:
        return {}
    try:
        dados = resposta.json()
    except Exception:
        return {}
    if isinstance(dados, list) and dados:
        return dados[0]
    return {}


def _alterar_tag_kit(email: str, acao: str) -> bool:
    tag_id = os.getenv("TAG_PIX_ID")
    if not tag_id or not email:
        return False

    if acao == "unsubscribe":
        credencial = os.getenv("CONVERTKIT_API_SECRET")
        campo_credencial = "api_secret"
    elif acao == "subscribe":
        credencial = os.getenv("CONVERTKIT_API_KEY")
        campo_credencial = "api_key"
    else:
        return False

    if not credencial:
        return False

    resposta = requests.post(
        f"{KIT_BASE_URL}/tags/{tag_id}/{acao}",
        json={campo_credencial: credencial, "email": email},
        timeout=5,
    )
    return resposta.status_code in (200, 201, 204)


def reconciliar_cancelamento(order_id: str, email_preferido: str = "") -> bool:
    ledger = buscar_ledger(order_id)
    status = _texto(ledger.get("status")).lower()
    if status == "cancelled":
        return True
    if status != "cancelled_pending_unsubscribe":
        return False

    email = _texto(email_preferido) or _texto(ledger.get("email"))
    if not email:
        return False

    try:
        removido = _alterar_tag_kit(email, "unsubscribe")
    except Exception as exc:
        print(f"[PIX Recovery] Falha no unsubscribe: {type(exc).__name__}")
        return False

    if not removido:
        print("[PIX Recovery] Unsubscribe permaneceu pendente")
        return False

    if bool(ledger.get("subscribe_attempted")):
        # Mantemos pending como evidencia duravel contra efeito remoto tardio.
        return True

    return confirmar_cancelamento(order_id)


def compensar_subscribe_concorrente(order_id: str, email: str, attempt_token: str) -> bool:
    reabrir_cancelamento(order_id, attempt_token)
    return reconciliar_cancelamento(order_id, email)


def processar_pix_criado(dados):
    if not _evento_pix_criado(dados):
        return

    info = _dados_pix(dados)
    order_id = info["order_id"]
    if not order_id:
        return

    venda = confirmar_venda_kiwify(
        order_id,
        statuses_aceitos=KIWIFY_PENDING_STATUSES,
        payment_method_esperado="pix",
    )
    email = _texto(venda.get("email"))
    if not venda or not email:
        return

    attempt_token = str(uuid4())

    try:
        if not adquirir_processamento(order_id, email, attempt_token):
            reconciliar_cancelamento(order_id, email)
            return

        if not transicionar(order_id, attempt_token, "processing", "subscribing"):
            reconciliar_cancelamento(order_id, email)
            return

        try:
            sucesso = _alterar_tag_kit(email, "subscribe")
        except Exception as exc:
            print(f"[PIX Recovery] Resultado ambiguo do subscribe: {type(exc).__name__}")
            if compensar_subscribe_concorrente(order_id, email, attempt_token):
                return
            transicionar(order_id, attempt_token, "subscribing", "failed")
            return

        if not sucesso:
            if compensar_subscribe_concorrente(order_id, email, attempt_token):
                return
            transicionar(order_id, attempt_token, "subscribing", "failed")
            return

        if not transicionar(order_id, attempt_token, "subscribing", "completed"):
            compensar_subscribe_concorrente(order_id, email, attempt_token)

    except Exception as exc:
        print(f"[PIX Recovery] Falha ao iniciar recovery: {type(exc).__name__}")
        try:
            if not compensar_subscribe_concorrente(order_id, email, attempt_token):
                transicionar(order_id, attempt_token, "subscribing", "failed")
        except Exception:
            pass


def cancelar_pix_por_pagamento(dados):
    if not _evento_pago(dados):
        return

    info = _dados_pix(dados)
    order_id = info["order_id"]
    if not order_id:
        return

    venda = confirmar_venda_kiwify(order_id, statuses_aceitos={"paid"})
    if not venda:
        return
    email = _texto(venda.get("email"))

    try:
        if not persistir_cancelamento(order_id, email):
            return

        reconciliar_cancelamento(order_id, email)
    except Exception as exc:
        print(f"[PIX Recovery] Falha ao cancelar recovery: {type(exc).__name__}")


@router.post("/kiwify")
async def webhook_kiwify_com_pix(request: Request, background_tasks: BackgroundTasks):
    dados = None
    eh_pix = False
    eh_pago = False

    # Classifica antes do handler original. Starlette reutiliza o corpo para JSON valido.
    # Em JSON invalido, o handler original continua sendo a fonte da resposta final.
    try:
        dados = await request.json()
        if isinstance(dados, dict):
            eh_pix = _evento_pix_criado(dados)
            eh_pago = _evento_pago(dados)
    except Exception:
        pass

    resposta = await webhook_kiwify(request, background_tasks)

    if dados is None:
        return resposta

    try:
        if eh_pix:
            background_tasks.add_task(processar_pix_criado, dados)
        elif eh_pago:
            background_tasks.add_task(cancelar_pix_por_pagamento, dados)
    except Exception as exc:
        print(f"[PIX Recovery] Falha ao agendar efeito adicional: {type(exc).__name__}")

    return resposta
