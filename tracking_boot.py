"""Bootstrap isolado do Lucas Tracking v1.

Importa a aplicacao existente sem alterar main.py e registra apenas as rotas
novas de tracking automatico. O fluxo com formulario de telefone fica fora do
bootstrap por decisao de arquitetura: tracking deve ser sem atrito.

No ambiente de teste, substitui somente POST /webhook por uma versao protegida
que preserva origem/campanha first-touch. A main de producao continua intacta.
"""

from main import app
from tracking_routes import router as tracking_router
from tracking_claim_routes import router as tracking_claim_router
from tracking_safe_webhook import router as tracking_safe_webhook_router

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
