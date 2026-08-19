"""Bootstrap isolado do Lucas Tracking v1.

Importa a aplicacao existente sem alterar main.py e registra apenas as rotas
novas de tracking automatico. O fluxo com formulario de telefone fica fora do
bootstrap por decisao de arquitetura: tracking deve ser sem atrito.

No ambiente de teste, substitui somente POST /webhook por uma versao protegida
que preserva origem/campanha first-touch. A main de producao continua intacta.
"""

from fastapi.middleware.cors import CORSMiddleware

from main import app
from journey_events import router as journey_events_router
from tracking_routes import router as tracking_router
from tracking_claim_routes import router as tracking_claim_router
from tracking_safe_webhook import router as tracking_safe_webhook_router
from recovery_routes import router as recovery_router

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

# Remove apenas a rota POST /webhook importada de main para evitar duas rotas
# concorrentes no servico de teste. /kiwify e todas as demais permanecem iguais.
app.router.routes = [
    rota
    for rota in app.router.routes
    if not (
        getattr(rota, "path", None) == "/webhook"
        and "POST" in (getattr(rota, "methods", set()) or set())
    )
]

app.include_router(tracking_safe_webhook_router)
app.include_router(tracking_router)
app.include_router(tracking_claim_router)
app.include_router(journey_events_router)
app.include_router(recovery_router)
