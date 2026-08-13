"""Bootstrap isolado do tracking.

Importa a aplicacao existente sem alterar main.py e registra apenas as rotas novas
de rastreamento. O servico de teste no Render deve iniciar este modulo.
"""

from main import app
from tracking_routes import router as tracking_router
from tracking_claim_routes import router as tracking_claim_router
from tracking_phone_routes import router as tracking_phone_router

app.include_router(tracking_router)
app.include_router(tracking_claim_router)
app.include_router(tracking_phone_router)
