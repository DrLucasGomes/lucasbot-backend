"""Convergencia de recuperacoes do Kit por estado real da Kiwify.

Este wrapper fica acima do handler Kiwify existente. Ele nao substitui a
persistencia, tracking, buyer tag, PIX/boleto ledger ou reconciliacao ja
existentes. Antes do processamento, protege compradores ja pagos contra novos
eventos de recuperacao. Depois que o processamento principal aceita o webhook,
remove tags de recuperacao incompatíveis para impedir sequencias concorrentes.

Para abandono de checkout, a transicao no Kit e feita de forma sincrona e
atomica do ponto de vista do webhook: garante a tag de abandono e remove a tag
de recuperacao pos-clique. Se qualquer etapa critica falhar, responde 503 para
a Kiwify reenviar o evento.
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
    """Consulta a verdade persistida antes de aceitar um novo estado de recuperacao."""
    if not valor_valido(email):
        return False

    lead = buscar_lead_existente(email=_texto(email))
    if not isinstance(lead, dict):
        return False

    status_atual = _texto(lead.get("status_pagamento")).lower()
    return status_atual in STATUS_PAGOS


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


def _tag_para_aplicar(estado: str) -> str:
    if estado == "abandoned":
        return "TAG_ABANDONO_ID"
    return ""


def convergir_tags_kit(email: str, estado: str) -> bool:
    """Converge o Kit para um unico estado de recuperacao coerente."""
    if not valor_valido(email):
        return False

    api_secret = _texto(os.getenv("CONVERTKIT_API_SECRET"))
    if not api_secret:
        print("[Recovery State] CONVERTKIT_API_SECRET ausente")
        return False

    payload = {"api_secret": api_secret, "email": _texto(email)}

    # No abandono, nao dependemos mais do background task do handler legado:
    # garantimos a entrada na trilha correta antes de remover a trilha anterior.
    env_aplicar = _tag_para_aplicar(estado)
    if env_aplicar:
        tag_aplicar = _texto(os.getenv(env_aplicar))
        if not tag_aplicar:
            print(f"[Recovery State] {env_aplicar} ausente")
            return False
        try:
            resposta = requests.post(
                f"{KIT_BASE_URL}/tags/{tag_aplicar}/subscribe",
                json=payload,
                timeout=10,
            )
            if resposta.status_code not in (200, 201, 204):
                print(
                    "[Recovery State] subscribe falhou "
                    f"estado={estado} tag_id={tag_aplicar} status_http={resposta.status_code}"
                )
                return False
            print(
                "[Recovery State] operation=subscribe "
                f"estado={estado} tag_id={tag_aplicar} status_http={resposta.status_code}"
            )
        except Exception as exc:
            print(
                "[Recovery State] subscribe falhou "
                f"estado={estado} tag_id={tag_aplicar} erro={type(exc).__name__}"
            )
            return False

    envs = _tags_para_remover(estado)
    if not envs:
        return True

    tags = []
    for env_name in envs:
        tag_id = _texto(os.getenv(env_name))
        if not tag_id:
            # Antes isso virava sucesso silencioso. Para transicoes criticas,
            # configuracao ausente deve falhar para podermos corrigir/reentregar.
            print(f"[Recovery State] {env_name} ausente")
            return False
        if tag_id not in tags:
            tags.append(tag_id)

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
            if not sucesso:
                return False
        except Exception as exc:
            print(
                "[Recovery State] unsubscribe falhou "
                f"estado={estado} tag_id={tag_id} erro={type(exc).__name__}"
            )
            return False

    return True


@router.post("/kiwify")
async def webhook_kiwify_com_estado(
    request: Request, background_tasks: BackgroundTasks
):
    """Protege paid terminal, executa o handler oficial e converge o Kit."""
    try:
        dados = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalido")

    estado = classificar_estado_recuperacao(dados)
    email = _email(dados)

    # paid e terminal: se um comprador antigo voltar ao checkout usando o mesmo
    # email, abandono/PIX/boleto novos nao podem rebaixar o Supabase nem reativar
    # qualquer recuperacao. A guarda roda ANTES do handler existente.
    if estado in ESTADOS_RECUPERACAO and email:
        try:
            if comprador_ja_pago(email):
                print(
                    "[Recovery State] evento ignorado para comprador pago "
                    f"estado={estado} email={email}"
                )
                return {
                    "status": "ignorado_comprador_ja_pago",
                    "status_pagamento": "paid",
                    "email": email,
                    "evento_ignorado": estado,
                }
        except Exception as exc:
            print(
                "[Recovery State] falha ao verificar paid terminal "
                f"estado={estado} erro={type(exc).__name__}"
            )
            raise HTTPException(
                status_code=503,
                detail="paid_terminal_guard_unavailable",
            )

    # O Request do Starlette faz cache de .json(), portanto o wrapper existente
    # pode ler o mesmo corpo sem consumir o stream pela segunda vez.
    resposta = await webhook_kiwify_com_pix(request, background_tasks)

    if not estado or not email:
        return resposta

    if not convergir_tags_kit(email, estado):
        raise HTTPException(
            status_code=503,
            detail="recovery_state_not_converged",
        )

    return resposta
