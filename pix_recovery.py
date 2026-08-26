import hmac
import os
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
from uuid import uuid4

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from kit_utils import (
    atualizar_first_name_kit,
    extrair_subscriber_id,
    metadados_resposta_subscribe,
    primeiro_nome as _primeiro_nome,
)
from main import STATUS_PAGOS, URL, obter_headers_supabase, valor_valido, webhook_kiwify


router = APIRouter(tags=["kiwify-pix-recovery"])

PIX_TABLE = "recovery_pix_orders"
PIX_JOB_TABLE = "recovery_pix_jobs"
KIT_BASE_URL = "https://api.convertkit.com/v3"
PROCESSING_STALE_MINUTES = 5
KIWIFY_API_BASE_URL = "https://public-api.kiwify.com/v1"
KIWIFY_PENDING_STATUSES = frozenset({"pending", "waiting_payment"})
KIWIFY_API_TIMEOUT_SECONDS = 5
PIX_JOB_STALE_MINUTES = 5
PIX_JOB_RECONCILE_LIMIT = 5

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


def _normalizar_boleto_link(valor) -> str:
    texto = _texto(valor)
    if not texto:
        return ""
    try:
        parsed = urlparse(texto)
    except Exception:
        return ""
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        return ""
    return texto


def _obter_oauth_token_kiwify() -> str:
    """Obtém e reutiliza o OAuth da Kiwify sem expor credenciais."""
    client_id = _texto(os.getenv("KIWIFY_API_CLIENT_ID"))
    client_secret = _texto(os.getenv("KIWIFY_API_CLIENT_SECRET"))
    agora = time.monotonic()
    token_cache = _texto(_kiwify_oauth_cache.get("access_token"))
    if token_cache and agora < float(_kiwify_oauth_cache.get("expires_at") or 0):
        return token_cache

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
        expires_valido = expires_in > 0
        if not access_token:
            return ""
        if not expires_valido:
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
    if not order_id:
        return {}
    if not account_id:
        return {}

    access_token = _obter_oauth_token_kiwify()
    if not access_token:
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
    if not isinstance(venda, dict):
        return {}

    identity_ok = _texto(venda.get("id")) == order_id
    status = _texto(venda.get("status")).lower()
    payment_method = _texto(venda.get("payment_method")).lower()
    customer = venda.get("customer") or venda.get("Customer")
    if not isinstance(customer, dict):
        customer = {}
    email = _texto(customer.get("email"))
    first_name = (
        _primeiro_nome(customer.get("first_name"))
        or _primeiro_nome(customer.get("name"))
        or _primeiro_nome(customer.get("full_name"))
    )
    boleto_url = _normalizar_boleto_link(
        venda.get("boleto_url") or venda.get("boleto_URL")
    )
    if not identity_ok:
        return {}

    statuses_normalizados = {_texto(item).lower() for item in statuses_aceitos}
    if status not in statuses_normalizados:
        return {}

    if payment_method_esperado and payment_method != _texto(payment_method_esperado).lower():
        return {}

    resultado = {
        "id": order_id,
        "status": status,
        "payment_method": payment_method,
        "email": email,
        "first_name": first_name,
    }
    if payment_method == "boleto" and boleto_url:
        resultado["boleto_url"] = boleto_url
    return resultado


def _evento_pix_criado(dados) -> bool:
    ordem = _ordem(dados)
    return (
        _texto(ordem.get("webhook_event_type")).lower() == "pix_created"
        and _texto(ordem.get("payment_method")).lower() == "pix"
        and _texto(ordem.get("order_status")).lower() == "waiting_payment"
        and bool(_texto(ordem.get("order_id")))
    )


def _evento_boleto_criado(dados) -> bool:
    ordem = _ordem(dados)
    return (
        _texto(ordem.get("webhook_event_type")).lower() == "billet_created"
        and _texto(ordem.get("payment_method")).lower() == "boleto"
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


def _parse_boleto_expiry_date(valor) -> str:
    texto = _texto(valor)
    if not texto:
        return ""
    try:
        data = datetime.strptime(texto, "%d/%m/%Y").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return ""
    return data.isoformat()


def _dados_boleto(dados):
    ordem = _ordem(dados)
    cliente = ordem.get("Customer") or ordem.get("customer") or {}
    if not isinstance(cliente, dict):
        cliente = {}
    return {
        "order_id": _texto(ordem.get("order_id")),
        "email": _texto(cliente.get("email") or cliente.get("Email")),
        "expires_at": _parse_boleto_expiry_date(ordem.get("boleto_expiry_date")),
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


def enfileirar_job_pix(
    order_id: str, event_type: str, expires_at: str = ""
) -> bool:
    payload = {"p_order_id": order_id, "p_event_type": event_type}
    if expires_at:
        payload["p_expires_at"] = expires_at
    return _rpc_bool(
        "recovery_pix_job_enqueue",
        payload,
    )


def adquirir_job_pix(order_id: str, event_type: str, attempt_token: str) -> bool:
    return _rpc_bool(
        "recovery_pix_job_acquire",
        {
            "p_order_id": order_id,
            "p_event_type": event_type,
            "p_attempt_token": attempt_token,
            "p_stale_minutes": PIX_JOB_STALE_MINUTES,
        },
    )


def concluir_job_pix(order_id: str, event_type: str, attempt_token: str) -> bool:
    return _rpc_bool(
        "recovery_pix_job_complete",
        {
            "p_order_id": order_id,
            "p_event_type": event_type,
            "p_attempt_token": attempt_token,
        },
    )


def falhar_job_pix(
    order_id: str,
    event_type: str,
    attempt_token: str,
    retryable: bool = True,
) -> bool:
    return _rpc_bool(
        "recovery_pix_job_fail",
        {
            "p_order_id": order_id,
            "p_event_type": event_type,
            "p_attempt_token": attempt_token,
            "p_retryable": retryable,
        },
    )


def listar_jobs_pix_recuperaveis(limit: int = PIX_JOB_RECONCILE_LIMIT) -> list[dict]:
    try:
        resposta = requests.get(
            f"{URL}/rest/v1/{PIX_JOB_TABLE}",
            params={
                "status": "in.(pending,retryable,processing)",
                "select": "order_id,event_type,expires_at",
                "order": "updated_at.asc",
                "limit": str(max(1, min(int(limit), 100))),
            },
            headers=obter_headers_supabase(),
            timeout=3,
        )
    except Exception as exc:
        print(f"[PIX Job] Falha ao consultar jobs: {type(exc).__name__}")
        return []
    if resposta.status_code != 200:
        print(f"[PIX Job] Consulta de jobs falhou: HTTP {resposta.status_code}")
        return []
    try:
        jobs = resposta.json()
    except Exception as exc:
        print(f"[PIX Job] Resposta invalida na reconciliacao: {type(exc).__name__}")
        return []
    if not isinstance(jobs, list):
        print("[PIX Job] Resposta invalida na reconciliacao: formato inesperado")
        return []
    normalizados = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        order_id = _texto(job.get("order_id"))
        event_type = _texto(job.get("event_type"))
        if not order_id or event_type not in {"pix_created", "billet_created", "paid"}:
            continue
        normalizado = {"order_id": order_id, "event_type": event_type}
        expires_at = _texto(job.get("expires_at"))
        if expires_at:
            normalizado["expires_at"] = expires_at
        normalizados.append(normalizado)
    return normalizados


def adquirir_processamento(
    order_id: str,
    email: str,
    attempt_token: str,
    payment_method: str | None = None,
    expires_at: str | None = None,
) -> bool:
    payload = {
        "p_order_id": order_id,
        "p_email": email,
        "p_attempt_token": attempt_token,
        "p_stale_minutes": PROCESSING_STALE_MINUTES,
    }
    if payment_method:
        payload["p_payment_method"] = payment_method
    if expires_at:
        payload["p_expires_at"] = expires_at
    return _rpc_bool(
        "recovery_pix_acquire",
        payload,
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


def persistir_cancelamento_metodo(
    order_id: str, email: str | None, payment_method: str
) -> bool:
    return _rpc_bool(
        "recovery_pix_cancel",
        {
            "p_order_id": order_id,
            "p_email": email or None,
            "p_payment_method": payment_method,
        },
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
            "select": "email,status,attempt_token,subscribe_attempted,payment_method,expires_at",
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


def _alterar_tag_kit(
    email: str,
    acao: str,
    first_name: str = "",
) -> bool:
    tag_id = os.getenv("TAG_PIX_ID")
    if not tag_id or not email:
        return False

    if acao not in {"subscribe", "unsubscribe"}:
        return False
    credencial = os.getenv("CONVERTKIT_API_SECRET")
    campo_credencial = "api_secret"

    if not credencial:
        return False

    payload = {campo_credencial: credencial, "email": email}

    resposta = requests.post(
        f"{KIT_BASE_URL}/tags/{tag_id}/{acao}",
        json=payload,
        timeout=5,
    )
    if acao == "subscribe":
        json_valid, subscriber_id_present, first_name_present = (
            metadados_resposta_subscribe(resposta)
        )
        print(
            "[PIX Recovery] operation=subscribe "
            f"status_http={resposta.status_code} json_valid={json_valid} "
            f"subscriber_id_present={subscriber_id_present} "
            f"first_name_present={first_name_present}"
        )
    tag_success = resposta.status_code in (200, 201, 204)
    if acao == "subscribe" and tag_success and first_name:
        subscriber_id = extrair_subscriber_id(resposta)
        if subscriber_id is not None:
            atualizar_first_name_kit(subscriber_id, first_name)
    return tag_success


def _alterar_tag_boleto_kit(
    email: str,
    acao: str,
    first_name: str = "",
    boleto_link: str = "",
) -> bool:
    tag_id = _texto(os.getenv("TAG_BOLETO_ID"))
    api_secret = _texto(os.getenv("CONVERTKIT_API_SECRET"))
    if not tag_id or not email or not api_secret or acao not in {"subscribe", "unsubscribe"}:
        return False

    payload = {"api_secret": api_secret, "email": email}
    first_name_normalizado = (
        _primeiro_nome(first_name) if valor_valido(first_name) else ""
    )
    link_normalizado = _normalizar_boleto_link(boleto_link)
    if acao == "subscribe" and first_name_normalizado:
        payload["first_name"] = first_name_normalizado
    if acao == "subscribe" and link_normalizado:
        payload["fields"] = {"boleto_link": link_normalizado}
    resposta = requests.post(
        f"{KIT_BASE_URL}/tags/{tag_id}/{acao}", json=payload, timeout=5
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


def reconciliar_cancelamento_boleto(order_id: str, email_preferido: str = "") -> bool:
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
        removido = _alterar_tag_boleto_kit(email, "unsubscribe")
    except Exception as exc:
        print(f"[Boleto Recovery] Falha no unsubscribe: {type(exc).__name__}")
        return False
    if not removido:
        print("[Boleto Recovery] Unsubscribe permaneceu pendente")
        return False
    if bool(ledger.get("subscribe_attempted")):
        return True
    return confirmar_cancelamento(order_id)


def compensar_subscribe_concorrente(order_id: str, email: str, attempt_token: str) -> bool:
    reabrir_cancelamento(order_id, attempt_token)
    return reconciliar_cancelamento(order_id, email)


def compensar_subscribe_boleto_concorrente(
    order_id: str, email: str, attempt_token: str
) -> bool:
    reabrir_cancelamento(order_id, attempt_token)
    return reconciliar_cancelamento_boleto(order_id, email)


def processar_pix_criado(dados):
    if not _evento_pix_criado(dados):
        return False

    info = _dados_pix(dados)
    order_id = info["order_id"]
    if not order_id:
        return False

    venda = confirmar_venda_kiwify(
        order_id,
        statuses_aceitos=KIWIFY_PENDING_STATUSES,
        payment_method_esperado="pix",
    )
    if not venda:
        ledger = buscar_ledger(order_id)
        if _texto(ledger.get("status")).lower() in {
            "cancelled",
            "cancelled_pending_unsubscribe",
        }:
            return True
        return False
    email = _texto(venda.get("email"))
    if not email:
        return False
    first_name = _primeiro_nome(venda.get("first_name"))
    attempt_token = str(uuid4())

    try:
        if not adquirir_processamento(order_id, email, attempt_token):
            ledger = buscar_ledger(order_id)
            if _texto(ledger.get("status")).lower() == "completed":
                return True
            return reconciliar_cancelamento(order_id, email)

        if not transicionar(order_id, attempt_token, "processing", "subscribing"):
            return reconciliar_cancelamento(order_id, email)

        try:
            if first_name:
                sucesso = _alterar_tag_kit(email, "subscribe", first_name)
            else:
                sucesso = _alterar_tag_kit(email, "subscribe")
        except Exception as exc:
            print(f"[PIX Recovery] Resultado ambiguo do subscribe: {type(exc).__name__}")
            if compensar_subscribe_concorrente(order_id, email, attempt_token):
                return True
            transicionar(order_id, attempt_token, "subscribing", "failed")
            return False

        if not sucesso:
            if compensar_subscribe_concorrente(order_id, email, attempt_token):
                return True
            transicionar(order_id, attempt_token, "subscribing", "failed")
            return False

        if not transicionar(order_id, attempt_token, "subscribing", "completed"):
            return compensar_subscribe_concorrente(order_id, email, attempt_token)
        return True

    except Exception as exc:
        print(f"[PIX Recovery] Falha ao iniciar recovery: {type(exc).__name__}")
        try:
            if not compensar_subscribe_concorrente(order_id, email, attempt_token):
                transicionar(order_id, attempt_token, "subscribing", "failed")
        except Exception:
            pass
        return False


def processar_boleto_criado(dados, expires_at_override: str = ""):
    if not _evento_boleto_criado(dados):
        return False

    info = _dados_boleto(dados)
    order_id = info["order_id"]
    expires_at = _texto(expires_at_override) or info["expires_at"]
    if not order_id:
        return False
    venda = confirmar_venda_kiwify(
        order_id,
        statuses_aceitos={"waiting_payment"},
        payment_method_esperado="boleto",
    )
    if not venda:
        ledger = buscar_ledger(order_id)
        if _texto(ledger.get("status")).lower() in {
            "cancelled",
            "cancelled_pending_unsubscribe",
        }:
            return True
        return False
    email = _texto(venda.get("email"))
    boleto_link = _normalizar_boleto_link(venda.get("boleto_url"))
    if not email or not boleto_link:
        return False
    first_name = _primeiro_nome(venda.get("first_name"))
    attempt_token = str(uuid4())

    try:
        if not adquirir_processamento(
            order_id, email, attempt_token, "boleto", expires_at or None
        ):
            ledger = buscar_ledger(order_id)
            if _texto(ledger.get("status")).lower() == "completed":
                return True
            return reconciliar_cancelamento_boleto(order_id, email)
        if not transicionar(order_id, attempt_token, "processing", "subscribing"):
            return reconciliar_cancelamento_boleto(order_id, email)
        try:
            sucesso = _alterar_tag_boleto_kit(
                email, "subscribe", first_name, boleto_link
            )
        except Exception as exc:
            print(f"[Boleto Recovery] Resultado ambiguo do subscribe: {type(exc).__name__}")
            if compensar_subscribe_boleto_concorrente(order_id, email, attempt_token):
                return True
            transicionar(order_id, attempt_token, "subscribing", "failed")
            return False
        if not sucesso:
            if compensar_subscribe_boleto_concorrente(order_id, email, attempt_token):
                return True
            transicionar(order_id, attempt_token, "subscribing", "failed")
            return False
        if not transicionar(order_id, attempt_token, "subscribing", "completed"):
            return compensar_subscribe_boleto_concorrente(
                order_id, email, attempt_token
            )
        return True
    except Exception as exc:
        print(f"[Boleto Recovery] Falha ao iniciar recovery: {type(exc).__name__}")
        try:
            if not compensar_subscribe_boleto_concorrente(
                order_id, email, attempt_token
            ):
                transicionar(order_id, attempt_token, "subscribing", "failed")
        except Exception:
            pass
        return False


def cancelar_pix_por_pagamento(dados):
    if not _evento_pago(dados):
        return False

    info = _dados_pix(dados)
    order_id = info["order_id"]
    if not order_id:
        return False

    venda = confirmar_venda_kiwify(order_id, statuses_aceitos={"paid"})
    if not venda:
        return False
    email = _texto(venda.get("email"))
    payment_method = _texto(venda.get("payment_method")).lower()

    try:
        if payment_method == "boleto":
            if not persistir_cancelamento_metodo(order_id, email, "boleto"):
                return False
            return reconciliar_cancelamento_boleto(order_id, email)
        if not persistir_cancelamento(order_id, email):
            return False

        return reconciliar_cancelamento(order_id, email)
    except Exception as exc:
        print(f"[PIX Recovery] Falha ao cancelar recovery: {type(exc).__name__}")
        return False


def _payload_minimo_job(order_id: str, event_type: str, expires_at: str = "") -> dict:
    if event_type == "pix_created":
        return {
            "order_id": order_id,
            "webhook_event_type": "pix_created",
            "payment_method": "pix",
            "order_status": "waiting_payment",
        }
    if event_type == "paid":
        return {
            "order_id": order_id,
            "webhook_event_type": "order_approved",
            "order_status": "paid",
        }
    if event_type == "billet_created":
        payload = {
            "order_id": order_id,
            "webhook_event_type": "billet_created",
            "payment_method": "boleto",
            "order_status": "waiting_payment",
        }
        if expires_at:
            try:
                data = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                payload["boleto_expiry_date"] = data.strftime("%d/%m/%Y")
            except (TypeError, ValueError):
                pass
        return payload
    return {}


def processar_job_pix(order_id: str, event_type: str, expires_at: str = "") -> bool:
    """Adquire um job durável e finaliza somente sob o mesmo fencing token."""
    order_id = _texto(order_id)
    event_type = _texto(event_type)
    if not order_id or event_type not in {"pix_created", "billet_created", "paid"}:
        return False

    attempt_token = str(uuid4())
    if not adquirir_job_pix(order_id, event_type, attempt_token):
        return False

    try:
        payload = _payload_minimo_job(order_id, event_type, expires_at)
        if event_type == "pix_created":
            sucesso = processar_pix_criado(payload)
        elif event_type == "billet_created":
            sucesso = processar_boleto_criado(payload, expires_at)
        else:
            sucesso = cancelar_pix_por_pagamento(payload)
    except Exception:
        sucesso = False

    if sucesso:
        concluido = concluir_job_pix(order_id, event_type, attempt_token)
        if not concluido:
            print("[PIX Job] Conclusao nao confirmada; aguardando stale recovery")
        return concluido

    retry_persistido = falhar_job_pix(
        order_id, event_type, attempt_token, retryable=True
    )
    if retry_persistido:
        print("[PIX Job] Processamento falhou; job marcado como retryable")
    else:
        print("[PIX Job] Falha ao persistir retry; aguardando stale recovery")
    return False


def reconciliar_jobs_pix(limit: int = PIX_JOB_RECONCILE_LIMIT) -> dict:
    jobs = listar_jobs_pix_recuperaveis(limit)
    tentados = 0
    concluidos = 0
    for job in jobs:
        tentados += 1
        if job.get("expires_at"):
            sucesso = processar_job_pix(
                job["order_id"], job["event_type"], job["expires_at"]
            )
        else:
            sucesso = processar_job_pix(job["order_id"], job["event_type"])
        if sucesso:
            concluidos += 1
        # Um retorno False também cobre disputa perdida. Não expomos IDs.
    return {"candidates": len(jobs), "completed": concluidos, "attempted": tentados}


def _autorizar_reconciliacao(request: Request) -> None:
    segredo = _texto(os.getenv("PIX_RECOVERY_WORKER_TOKEN"))
    authorization = _texto(request.headers.get("Authorization"))
    prefixo = "Bearer "
    recebido = authorization[len(prefixo) :] if authorization.startswith(prefixo) else ""
    if not segredo or not recebido or not hmac.compare_digest(recebido, segredo):
        raise HTTPException(status_code=401, detail="nao autorizado")


@router.post("/internal/recovery-pix/reconcile")
async def reconciliar_jobs_pix_endpoint(request: Request):
    _autorizar_reconciliacao(request)
    return reconciliar_jobs_pix()


@router.post("/kiwify")
async def webhook_kiwify_com_pix(request: Request, background_tasks: BackgroundTasks):
    dados = None
    eh_pix = False
    eh_boleto = False
    eh_pago = False

    # Classifica antes do handler original. Starlette reutiliza o corpo para JSON valido.
    # Em JSON invalido, o handler original continua sendo a fonte da resposta final.
    try:
        dados = await request.json()
        if isinstance(dados, dict):
            eh_pix = _evento_pix_criado(dados)
            eh_boleto = _evento_boleto_criado(dados)
            eh_pago = _evento_pago(dados)
    except Exception:
        pass

    event_type = (
        "pix_created"
        if eh_pix
        else "billet_created"
        if eh_boleto
        else "paid"
        if eh_pago
        else ""
    )
    order_id = _dados_pix(dados).get("order_id") if event_type else ""
    expires_at = _dados_boleto(dados).get("expires_at", "") if eh_boleto else ""
    job_persistido = True
    if event_type:
        if eh_boleto and expires_at:
            job_persistido = enfileirar_job_pix(order_id, event_type, expires_at)
        else:
            job_persistido = enfileirar_job_pix(order_id, event_type)

    resposta = await webhook_kiwify(request, background_tasks)

    if not job_persistido:
        print("[PIX Job] Falha ao persistir evento antes do ACK")
        raise HTTPException(status_code=503, detail="evento nao persistido")

    if dados is None:
        return resposta

    try:
        if eh_boleto and expires_at:
            background_tasks.add_task(
                processar_job_pix, order_id, event_type, expires_at
            )
        elif eh_pix or eh_boleto:
            background_tasks.add_task(processar_job_pix, order_id, event_type)
        elif eh_pago:
            background_tasks.add_task(processar_job_pix, order_id, event_type)
    except Exception as exc:
        print(f"[PIX Recovery] Falha ao agendar efeito adicional: {type(exc).__name__}")

    return resposta