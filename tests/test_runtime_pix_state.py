from fastapi import FastAPI
from fastapi.testclient import TestClient

import pix_recovery


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _client():
    app = FastAPI()
    app.include_router(pix_recovery.router)
    return TestClient(app)


def test_runtime_pix_state_exige_token_sem_consultar_supabase(monkeypatch):
    monkeypatch.setenv("PIX_RECOVERY_WORKER_TOKEN", "worker-secret")
    chamadas = []
    monkeypatch.setattr(
        pix_recovery.requests,
        "get",
        lambda *args, **kwargs: chamadas.append((args, kwargs)),
    )

    resposta = _client().get("/internal/e2e/runtime-pix-state")

    assert resposta.status_code == 401
    assert chamadas == []


def test_runtime_pix_state_retorna_somente_estado_sanitizado(monkeypatch):
    segredo = "worker-secret"
    monkeypatch.setenv("PIX_RECOVERY_WORKER_TOKEN", segredo)
    capturado = {}

    def fake_get(url, headers=None, timeout=None):
        capturado.update({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse(
            payload={
                "paths": {
                    "/recovery_pix_jobs": {},
                    "/rpc/recovery_pix_job_enqueue": {},
                    "/recovery_pix_orders": {},
                    "/rpc/recovery_pix_acquire": {},
                }
            }
        )

    monkeypatch.setattr(pix_recovery.requests, "get", fake_get)

    resposta = _client().get(
        "/internal/e2e/runtime-pix-state",
        headers={"Authorization": f"Bearer {segredo}"},
    )

    assert resposta.status_code == 200
    assert resposta.json() == {
        "git_marker": "91862b15",
        "pix_route_wrapper_active": True,
        "supabase_project_ref": "gwxcnczuwfrswhkzflaw",
        "job_rpc_available": True,
        "ledger_rpc_available": True,
    }
    assert capturado["url"] == f"{pix_recovery.URL}/rest/v1/"
    assert capturado["headers"]["Accept"] == "application/openapi+json"
    assert capturado["timeout"] == 3
    assert segredo not in resposta.text


def test_runtime_pix_state_falha_de_schema_retorna_apenas_false(monkeypatch):
    segredo = "worker-secret"
    monkeypatch.setenv("PIX_RECOVERY_WORKER_TOKEN", segredo)
    monkeypatch.setattr(
        pix_recovery.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(404, {"segredo": segredo}),
    )

    resposta = _client().get(
        "/internal/e2e/runtime-pix-state",
        headers={"Authorization": f"Bearer {segredo}"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["job_rpc_available"] is False
    assert resposta.json()["ledger_rpc_available"] is False
    assert segredo not in resposta.text
