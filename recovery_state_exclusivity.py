"""Convergencia das recuperacoes do Kit a partir do estado real da Kiwify.

Aceita os envelopes historicos ``{order:{...}}`` / ``{cart:{...}}`` e tambem
os payloads achatados observados nos reenvios reais da Kiwify.
"""

import os

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from main import STATUS_ABANDONO, STATUS_PAGOS, buscar_lead_existente, valor_valido
from pix_recovery import webhook_kiwify_com_pix


router = APIRouter(tags=["kiwify-recovery-state"])
KIT_BASE_URL = "https://api.convertkit.com/v3"
ESTADOS_RECUPERACAO = {"abandoned", "pix_pending", "boleto_pending"}


def _texto(valor) -> str:
    return str(valor or "").strip()


def _ordem(dados: dict) -> dict:
    if not isinstance(dados, dict):
        return {}

    ordem = dados.get("order") or dados.get("Order")
    if isinstance(ordem, dict):
        return ordem

    if any(
        chave in dados
        for chave in ("order_status", "webhook_event_type", "payment_method", "Customer", "customer")
    ):
        return dados

    return {}


def _carrinho(dados: dict) -> dict:
    if not isinstance(dados, dict):
        return {}

    carrinho = dados.get("cart") or dados.get("Cart")
    if isinstance(carrinho, dict):
        return carrinho

    if valor_valido(dados.get("status")) and any(
        chave in dados for chave in ("checkout_link", "product_id", "offer_name", "store_id")
    ):
        return dados

    return {}


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
    ordem = _ordem(dados)
    carrinho = _carrinho(dados)

    order_status = _texto(ordem.get("order_status")).lower()
    event_type = _texto(ordem.get("webhook_event_type")).lower()
    payment_method = _texto(ordem.get("payment_method")).lower()
    cart_status = _texto(carrinho.get("status")).lower()

    if order_status in STATUS_PAGOS or event_type in STATUS_PAGOS:
        return "paid"
    if event_type == "pix_created" and payment_method == "pix" and order_status == "waiting_payment":
        return "pix_pending"
    if event_type == "billet_created" and payment_method == "boleto" and order_status == "waiting_payment":
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

    return _texto(lead.get("status_pagamento")).lower() in STATUS_PAGOS


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
        print("[Recovery State] configuracao de abandono ausente")
        return False

    try:
        resposta = requests.post(
            f"{KIT_BASE_URL}/tags/{tag_id}/subscribe",
            json={"api_secret": api_secret, "email": _texto(email)},
            timeout=10,
        )
    except Exception as exc:
        print(f"[Recovery State] falha ao aplicar abandono erro={type(exc).__name__}")
        return False

    if resposta.status_code not in (200, 201, 204):
        print(f"[Recovery State] Kit recusou abandono status_http={resposta.status_code}")
        return False

    return True


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
            resposta = requests.post(
                f"{KIT_BASE_URL}/tags/{tag_id}/unsubscribe",
                json=payload,
                timeout=10,
            )
        except Exception as exc:
            print(
                f"[Recovery State] falha ao remover tag estado={estado} "
                f"tag_id={tag_id} erro={type(exc).__name__}"
            )
            return False

        if resposta.status_code not in (200, 201, 204):
            print(
                f"[Recovery State] Kit recusou remocao estado={estado} "
                f"tag_id={tag_id} status_http={resposta.status_code}"
            )
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

    if estado in ESTADOS_RECUPERACAO and email:
        try:
            if comprador_ja_pago(email):
                return {
                    "status": "ignorado_comprador_ja_pago",
                    "status_pagamento": "paid",
                    "email": email,
                    "evento_ignorado": estado,
                }
        except Exception as exc:
            print(
                f"[Recovery State] falha ao verificar paid terminal "
                f"estado={estado} erro={type(exc).__name__}"
            )
            raise HTTPException(status_code=503, detail="paid_terminal_guard_unavailable")

    resposta = await webhook_kiwify_com_pix(request, background_tasks)
    if not estado or not email:
        return resposta

    if not garantir_tag_estado_kit(email, estado):
        raise HTTPException(status_code=503, detail="recovery_state_entry_not_converged")
    if not convergir_tags_kit(email, estado):
        raise HTTPException(status_code=503, detail="recovery_state_not_converged")

    return resposta
