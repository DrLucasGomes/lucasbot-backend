"""Bootstrap isolado do Lucas Tracking v1.

Importa a aplicacao existente sem alterar main.py e registra apenas as rotas
novas de tracking automatico. O fluxo com formulario de telefone fica fora do
bootstrap por decisao de arquitetura: tracking deve ser sem atrito.

No ambiente de teste, substitui POST /webhook por uma versao protegida que
preserva origem/campanha first-touch. POST /kiwify preserva o processamento
existente e acrescenta apenas a recuperacao idempotente de PIX.
"""

import requests
from fastapi.middleware.cors import CORSMiddleware

from main import app, obter_headers_supabase
from journey_events import router as journey_events_router
from tracking_routes import router as tracking_router
from tracking_claim_routes import router as tracking_claim_router
from tracking_safe_webhook import router as tracking_safe_webhook_router
from recovery_routes import router as recovery_router
import pix_recovery
from pix_recovery import router as pix_recovery_router


def _rpc_bool_debug(nome: str, payload: dict) -> bool:
    """Instrumentacao temporaria e sanitizada para o E2E PIX.

    Registra somente nome da RPC, HTTP status e corpo retornado pelo PostgREST.
    Nao registra headers, chaves, email, order_id ou payload enviado.
    """
    try:
        resposta = requests.post(
            f"{pix_recovery.URL}/rest/v1/rpc/{nome}",
            json=payload,
            headers=obter_headers_supabase(),
            timeout=3,
        )
    except Exception as exc:
        print(f"[PIX RPC DEBUG] rpc={nome} exception={type(exc).__name__}: {str(exc)}")
        return False

    corpo = resposta.text[:500].replace("\n", " ")
    print(
        f"[PIX RPC DEBUG] rpc={nome} status={resposta.status_code} response={corpo}"
    )

    if resposta.status_code != 200:
        return False

    try:
        return resposta.json() is True
    except Exception:
        return False


# Instrumentacao temporaria apenas nesta branch de teste. Remover antes do merge.
pix_recovery._rpc_bool = _rpc_bool_debug


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://drlucasgomes.com.br",
        "https://www.drlucasgomes.com.br",
    ],
    allow_credentials=False,
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

# Remove somente as rotas que recebem wrappers protegidos/aditivos neste
# bootstrap. As funcoes originais continuam sendo chamadas pelos wrappers.
app.router.routes = [
    rota
    for rota in app.router.routes
    if not (
        getattr(rota, "path", None) in {"/webhook", "/kiwify"}
        and "POST" in (getattr(rota, "methods", set()) or set())
    )
]

app.include_router(tracking_safe_webhook_router)
app.include_router(pix_recovery_router)
app.include_router(tracking_router)
app.include_router(tracking_claim_router)
app.include_router(journey_events_router)
app.include_router(recovery_router)
