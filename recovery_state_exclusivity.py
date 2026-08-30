"""Convergencia de recuperacoes do Kit por estado real da Kiwify.

Este wrapper fica acima do handler Kiwify existente. Ele nao substitui a
persistencia, tracking, buyer tag, PIX/boleto ledger ou reconciliacao ja
existentes. Depois que o processamento principal aceita o webhook, remove tags
de recuperacao incompatíveis para impedir sequencias concorrentes no Kit.

A Kiwify recebe HTTP 503 quando uma remocao configurada falha. Assim a
reentrega do webhook funciona como retry externo, enquanto PIX/boleto continuam
protegidos pela inbox duravel e pelo reconciliador existentes.
"""

import os

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from main import STATUS_ABANDONO, STATUS_PAGOS, valor_valido
from pix_recovery import webhook_kiwify_com_pix


router = APIRouter(tags=["kiwify-recovery-state"])
KIT_BASE_URL = "https://api.convertkit.com/v3"


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


def _tags_para_remover(estado: str) -> tuple[str, ...]:
    """Retorna nomes das env vars cujas tags sao incompatíveis com o estado."""
    if estado == "abandoned":
        return ("TAG_RECUPERACAO_VIDEO_ID",)
    if estado == "pix_pending":
        return (
            "TAG_RECUPERACAO_VIDEO_ID",
            "TAG_ABANDONO_ID",
            "TAG_BOLETO_ID",
        )
    if estado == "boleto_pending":
        return (
            "TAG_RECUPERACAO_VIDEO_ID",
            "TAG_ABANDONO_ID",
            "TAG_PIX_ID",
        )
    if estado == "paid":
        return (
            "TAG_RECUPERACAO_VIDEO_ID",
            "TAG_ABANDONO_ID",
            "TAG_PIX_ID",
            "TAG_BOLETO_ID",
        )
    return ()


def convergir_tags_kit(email: str, estado: str) -> bool:
    """Remove todas as recuperacoes incompatíveis configuradas para o estado."""
    if not valor_valido(email):
        return False

    envs = _tags_para_remover(estado)
    if not envs:
        return True

    tags = []
    for env_name in envs:
        tag_id = _texto(os.getenv(env_name))
        if tag_id and tag_id not in tags:
            tags.append(tag_id)

    # Nenhuma tag configurada para esse estado: nao ha efeito remoto a executar.
    if not tags:
        return True

    api_secret = _texto(os.getenv("CONVERTKIT_API_SECRET"))
    if not api_secret:
        print("[Recovery State] CONVERTKIT_API_SECRET ausente")
        return False

    payload = {"api_secret": api_secret, "email": _texto(email)}
    sucesso_total = True

    for tag_id in tags:
        try:
            resposta = requests.post(
                f"{KIT_BASE_URL}/tags/{tag_id}/unsubscribe",
                json=payload,
                timeout=10,
            )
            sucesso = resposta.status_code in (200, 201, 204)
            print(
                "[Recovery State] operation=unsubscribe "
                f"estado={estado} tag_id={tag_id} status_http={resposta.status_code}"
            )
            sucesso_total = sucesso_total and sucesso
        except Exception as exc:
            print(
                "[Recovery State] unsubscribe falhou "
                f"estado={estado} tag_id={tag_id} erro={type(exc).__name__}"
            )
            sucesso_total = False

    return sucesso_total


@router.post("/kiwify")
async def webhook_kiwify_com_estado(
    request: Request, background_tasks: BackgroundTasks
):
    """Executa o handler oficial uma vez e depois converge recuperacoes no Kit."""
    try:
        dados = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalido")

    # O Request do Starlette faz cache de .json(), portanto o wrapper existente
    # pode ler o mesmo corpo sem consumir o stream pela segunda vez.
    resposta = await webhook_kiwify_com_pix(request, background_tasks)

    estado = classificar_estado_recuperacao(dados)
    if not estado:
        return resposta

    email = _email(dados)
    if not email:
        # O handler principal ja decide como responder a payload sem identidade.
        return resposta

    if not convergir_tags_kit(email, estado):
        # Forca reentrega Kiwify. O processamento principal e os jobs PIX/boleto
        # sao idempotentes/deduplicados, entao o retry converge sem venda dupla.
        raise HTTPException(
            status_code=503,
            detail="recovery_state_not_converged",
        )

    return resposta
