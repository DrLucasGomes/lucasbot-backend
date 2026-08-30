"""Bootstrap isolado do Lucas Tracking v1.

Importa a aplicacao existente sem alterar main.py e registra apenas as rotas
novas de tracking automatico. O fluxo com formulario de telefone fica fora do
bootstrap por decisao de arquitetura: tracking deve ser sem atrito.

POST /kiwify passa por uma camada de convergencia de recuperacoes e, em seguida,
reutiliza o wrapper existente de PIX/boleto. As rotas internas do reconciliador
PIX/boleto continuam registradas pelo router original.
"""

from fastapi.middleware.cors import CORSMiddleware

from main import app
from journey_events import router as journey_events_router
from tracking_routes import router as tracking_router
from tracking_claim_routes import router as tracking_claim_router
from tracking_safe_webhook import router as tracking_safe_webhook_router
from recovery_routes import router as recovery_router
from recovery_state_exclusivity import router as recovery_state_router
from pix_recovery import router as pix_recovery_router


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
# Precisa vir antes de pix_recovery_router: ambos expoem POST /kiwify, mas este
# wrapper e o ponto de entrada oficial e chama o handler PIX/boleto diretamente.
app.include_router(recovery_state_router)
# Mantido para registrar /internal/recovery-pix/reconcile e demais rotas
# internas. O POST /kiwify duplicado fica sombreado pelo router acima.
app.include_router(pix_recovery_router)
app.include_router(tracking_router)
app.include_router(tracking_claim_router)
app.include_router(journey_events_router)
app.include_router(recovery_router)
