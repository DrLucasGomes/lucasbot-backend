"""Convergencia de recuperacoes do Kit por estado real da Kiwify.

Este wrapper fica acima do handler Kiwify existente. Ele nao substitui a
persistencia, tracking, buyer tag, PIX/boleto ledger ou reconciliacao ja
existentes. Antes do processamento, protege compradores ja pagos contra novos
eventos de recuperacao. Depois que o processamento principal aceita o webhook,
remove tags de recuperacao incompatíveis para impedir sequencias concorrentes.

Para abandono de checkout, a entrada na tag de abandono e garantida de forma
sincrona antes da limpeza da recuperacao pos-clique. Falha critica retorna 503
para permitir reentrega do webhook.
"""

import os

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from main import (
    STATUS_ABANDONO,
    STATUS_PAGOS,
    buscar_lead_existente,
    valor_valido,
)
from pix_recovery import webhook_kiwify_com_pix


router = APIRouter(tags=["kiwify-recovery-state"])
KIT_BASE_URL = "https://api.convertkit.com/v3"
ESTADOS_RECUPERACAO = {"abandoned", "pix_pending", "boleto_pending"}


def _texto(valor) -> str:
    return str(valor or "").strip()


def _ordem(dados: dict) -> dict:
    ordem = dados.get("order") or dados.get("Order") or {}
    return ordem if isinstance(ordem, dict) else {}


def _carrinho(dados: dict) -> dict:
    carrinho = dados.get("cart") or dados.get("Cart") or {}
    return carrinho if isinstance(carrinho, dict) else {}


def _email(dados: dict) -> str:
    ordem = _ordem(dados)
    customer = ordem.get("Customer") or ordem.get("customer") or {}
    if isinstance(customer, dict) and valor_valido(customer.get("email")):
        return _texto(customer.get("email"))

    carrinho = _carrinho(dados)
    if valor_valido(carrinho.get("email")):
        return _texto(carrinho.get("email"))

    return _texto(dados.get("email"))


def classificar_estado_recuperacao(dados: dict) -> str:
    """Classifica somente eventos que alteram a trilha de recuperacao."""
    ordem = _ordem(dados)
    carrinho = _carrinho(dados)

    order_status = _texto(ordem.get("order_status")).lower()
    event_type = _texto(ordem.get("webhook_event_type")).lower()
    payment_method = _texto(ordem.get("payment_method")).lower()
    cart_status = _texto(carrinho.get("status")).lower()

    print(
        "[Recovery State] CLASSIFY "
        f"top_keys={sorted(dados.keys()) if isinstance(dados, dict) else 'not-dict'} "
        f"cart_type={type(carrinho).__name__} "
        f"cart_status={cart_status!r} order_status={order_status!r} "
        f"event_type={event_type!r} payment_method={payment_method!r} "
        f"status_abandono={sorted(STATUS_ABANDONO)}"
    )

    if order_status in STATUS_PAGOS or event_type in STATUS_PAGOS:
        return "paid"

    if (
        event_type == "pix_created"
        and payment_method == "pix"
        and order_status == "waiting_payment"
    ):
        return "pix_pending"

    if (
        event_type == "billet_created"
        and payment_method == "boleto"
        and order_status == "waiting_payment"
    ):
        return "boleto_pending"

    if cart_status in STATUS_ABANDONO or order_status in STATUS_ABANDONO:
        return "abandoned"

    return ""


def comprador_ja_pago(email: str) -> bool:
    if not valor_valido(email):
        return False
    lead = buscar_lead_existente(email=_texto(email))
    if not isinstance(lead, dict):
        return False
    status_atual = _texto(lead.get("status_pagamento")).lower()
    return status_atual in STATUS_PAGOS


def _tags_para_remover(estado: str) -> tuple[str, ...]:
    if estado == "abandoned":
        return ("TAG_RECUPERACAO_VIDEO_ID",)
    if estado == "pix_pending":
        return ("TAG_RECUPERACAO_VIDEO_ID", "TAG_ABANDONO_ID", "TAG_BOLETO_ID")
    if estado == "boleto_pending":
        return ("TAG_RECUPERACAO_VIDEO_ID", "TAG_ABANDONO_ID", "TAG_PIX_ID")
    if estado == "paid":
        return ("TAG_RECUPERACAO_VIDEO_ID", "TAG_ABANDONO_ID", "TAG_PIX_ID", "TAG_BOLETO_ID")
    return ()


def garantir_tag_estado_kit(email: str, estado: str) -> bool:
    if estado != "abandoned":
        return True
    if not valor_valido(email):
        return False
    api_secret = _texto(os.getenv("CONVERTKIT_API_SECRET"))
    tag_id = _texto(os.getenv("TAG_ABANDONO_ID"))
    if not api_secret or not tag_id:
        print("[Recovery State] credencial/tag de abandono ausente")
        return False
    try:
        resposta = requests.post(
            f"{KIT_BASE_URL}/tags/{tag_id}/subscribe",
            json={"api_secret": api_secret, "email": _texto(email)}, timeout=10,
        )
    except Exception as exc:
        print(f"[Recovery State] abandoned subscribe falhou erro={type(exc).__name__}")
        return False
    sucesso = resposta.status_code in (200, 201, 204)
    print(f"[Recovery State] operation=subscribe estado={estado} tag_id={tag_id} status_http={resposta.status_code}")
    return sucesso


def convergir_tags_kit(email: str, estado: str) -> bool:
    if not valor_valido(email):
        return False
    envs = _tags_para_remover(estado)
    if not envs:
        return True
    api_secret = _texto(os.getenv("CONVERTKIT_API_SECRET"))
    if not api_secret:
        print("[Recovery State] CONVERTKIT_API_SECRET ausente")
        return False
    tags = []
    for env_name in envs:
        tag_id = _texto(os.getenv(env_name))
        if not tag_id:
            print(f"[Recovery State] {env_name} ausente")
            return False
        if tag_id not in tags:
            tags.append(tag_id)
    payload = {"api_secret": api_secret, "email": _texto(email)}
    for tag_id in tags:
        try:
            endpoint = f"{KIT_BASE_URL}/tags/{tag_id}/unsubscribe"
            print(f"[Recovery State] operation=unsubscribe START estado={estado} email={email} tag_id={tag_id} endpoint={endpoint}")
            resposta = requests.post(endpoint, json=payload, timeout=10)
            body = _texto(getattr(resposta, "text", ""))[:500]
            sucesso = resposta.status_code in (200, 201, 204)
            print(f"[Recovery State] operation=unsubscribe END estado={estado} tag_id={tag_id} status_http={resposta.status_code} body={body!r}")
            if not sucesso:
                return False
        except Exception as exc:
            print(f"[Recovery State] unsubscribe falhou estado={estado} tag_id={tag_id} erro={type(exc).__name__}")
            return False
    return True


@router.post("/kiwify")
async def webhook_kiwify_com_estado(request: Request, background_tasks: BackgroundTasks):
    try:
        dados = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalido")

    estado = classificar_estado_recuperacao(dados)
    email = _email(dados)
    print(
        "[Recovery State] ENTRY "
        f"path={request.url.path} estado={estado or 'none'} email={email or 'none'} "
        f"tag_video={_texto(os.getenv('TAG_RECUPERACAO_VIDEO_ID')) or 'missing'} "
        f"tag_abandono={_texto(os.getenv('TAG_ABANDONO_ID')) or 'missing'}"
    )

    if estado in ESTADOS_RECUPERACAO and email:
        try:
            if comprador_ja_pago(email):
                print(f"[Recovery State] evento ignorado para comprador pago estado={estado} email={email}")
                return {"status": "ignorado_comprador_ja_pago", "status_pagamento": "paid", "email": email, "evento_ignorado": estado}
        except Exception as exc:
            print(f"[Recovery State] falha ao verificar paid terminal estado={estado} erro={type(exc).__name__}")
            raise HTTPException(status_code=503, detail="paid_terminal_guard_unavailable")

    resposta = await webhook_kiwify_com_pix(request, background_tasks)

    if not estado or not email:
        print(f"[Recovery State] EXIT sem convergencia estado={estado or 'none'} email={email or 'none'}")
        return resposta

    if not garantir_tag_estado_kit(email, estado):
        raise HTTPException(status_code=503, detail="recovery_state_entry_not_converged")
    if not convergir_tags_kit(email, estado):
        raise HTTPException(status_code=503, detail="recovery_state_not_converged")

    print(f"[Recovery State] EXIT convergido estado={estado} email={email}")
    return resposta
