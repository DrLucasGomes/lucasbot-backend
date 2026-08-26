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


def _bloquear_durable(monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("caminho durable nao deve ser chamado")

    for nome in (
        "enfileirar_job_pix",
        "adquirir_job_pix",
        "adquirir_processamento",
        "transicionar",
        "buscar_ledger",
        "reconciliar_jobs_pix",
        "webhook_kiwify",
    ):
        monkeypatch.setattr(pix_recovery, nome, proibido)


def test_endpoint_e2e_exige_token_antes_de_integracoes(monkeypatch):
    monkeypatch.setenv("PIX_RECOVERY_WORKER_TOKEN", "worker-secret")
    chamadas = []
    monkeypatch.setattr(
        pix_recovery.requests,
        "get",
        lambda *args, **kwargs: chamadas.append((args, kwargs)),
    )

    resposta = _client().post("/internal/e2e/pix-first-name/order-test")

    assert resposta.status_code == 401
    assert chamadas == []


def test_endpoint_e2e_executa_confirmacao_subscribe_e_put_sem_durable(
    monkeypatch, capsys
):
    segredo = "worker-secret"
    order_id = "order-test"
    monkeypatch.setenv("PIX_RECOVERY_WORKER_TOKEN", segredo)
    monkeypatch.setenv("KIWIFY_ACCOUNT_ID", "account-id")
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "kit-secret")
    monkeypatch.setattr(
        pix_recovery, "_obter_oauth_token_kiwify", lambda: "oauth-token"
    )
    _bloquear_durable(monkeypatch)

    def fake_get(url, **kwargs):
        assert url.endswith(f"/sales/{order_id}")
        return FakeResponse(
            200,
            {
                "id": order_id,
                "status": "waiting_payment",
                "payment_method": "pix",
                "Customer": {
                    "email": "pessoa@example.com",
                    "first_name": "Maria de Souza",
                    "name": "Nome Secundario",
                    "full_name": "Nome Terciario",
                },
            },
        )

    monkeypatch.setattr(pix_recovery.requests, "get", fake_get)
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(
            200, {"subscription": {"subscriber": {"id": 123}}}
        ),
    )
    puts = []
    monkeypatch.setattr(
        pix_recovery.requests,
        "put",
        lambda url, **kwargs: puts.append((url, kwargs)) or FakeResponse(200),
    )

    resposta = _client().post(
        f"/internal/e2e/pix-first-name/{order_id}",
        headers={"Authorization": f"Bearer {segredo}"},
    )

    assert resposta.status_code == 200
    assert resposta.json() == {
        "sale_confirmed": True,
        "first_name_present": True,
        "tag_subscribe_success": True,
        "subscriber_id_valid": True,
        "first_name_put_success": True,
    }
    assert puts[0][1]["json"]["first_name"] == "Maria"
    logs = capsys.readouterr().out
    for sensivel in (
        order_id,
        "pessoa@example.com",
        "Maria",
        "123",
        segredo,
        "kit-secret",
        "oauth-token",
    ):
        assert sensivel not in logs
        assert sensivel not in resposta.text


def test_endpoint_e2e_falha_put_nao_quebra_sucesso_da_tag(monkeypatch):
    segredo = "worker-secret"
    monkeypatch.setenv("PIX_RECOVERY_WORKER_TOKEN", segredo)
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "kit-secret")
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_venda_kiwify",
        lambda *args, **kwargs: {
            "email": "pessoa@example.com",
            "first_name": "Maria",
        },
    )
    _bloquear_durable(monkeypatch)
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(
            200, {"subscription": {"subscriber": {"id": 123}}}
        ),
    )
    monkeypatch.setattr(
        pix_recovery.requests,
        "put",
        lambda *args, **kwargs: FakeResponse(500),
    )

    resposta = _client().post(
        "/internal/e2e/pix-first-name/order-test",
        headers={"Authorization": f"Bearer {segredo}"},
    )

    assert resposta.json() == {
        "sale_confirmed": True,
        "first_name_present": True,
        "tag_subscribe_success": True,
        "subscriber_id_valid": True,
        "first_name_put_success": False,
    }
