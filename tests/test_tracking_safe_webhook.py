from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import main
import tracking_safe_webhook


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload if payload is not None else []

    def json(self):
        return self.payload


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(tracking_safe_webhook.router)
    return TestClient(app)


def _instalar_supabase(monkeypatch, capturado):
    def fake_get(*args, **kwargs):
        return FakeResponse(200, [])

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        capturado.update(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        return FakeResponse(201, [{"ok": True}])

    monkeypatch.setattr(tracking_safe_webhook.requests, "get", fake_get)
    monkeypatch.setattr(tracking_safe_webhook.requests, "post", fake_post)


def test_wrapper_com_nome_normaliza_e_encaminha_first_name(
    monkeypatch, client, capsys
):
    chamadas_kit = []
    persistido = {}
    _instalar_supabase(monkeypatch, persistido)
    monkeypatch.setattr(
        main,
        "adicionar_lead_convertkit",
        lambda *args: chamadas_kit.append(args),
    )

    resposta = client.post(
        "/webhook",
        json={
            "manychat_id": "abc123",
            "email": "lead@example.com",
            "nome": "Lucas Felipe Gomes",
        },
    )

    assert chamadas_kit == [("lead@example.com", "Lucas")]
    assert persistido["json"] == {
        "manychat_id": "abc123",
        "email": "lead@example.com",
        "nome": "Lucas Felipe Gomes",
    }
    assert persistido["url"].endswith(
        "/rest/v1/leads_vigor?on_conflict=manychat_id"
    )
    assert "resolution=merge-duplicates" in persistido["headers"]["Prefer"]
    assert persistido["timeout"] == 15
    assert resposta.json() == {
        "status": "sucesso",
        "code": 201,
        "payload_enviado": persistido["json"],
        "origem_preservada": False,
        "campanha_preservada": False,
        "convertkit_lead_agendado": True,
        "resposta_supabase": [{"ok": True}],
    }
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("nome", [None, "", "   ", "{{nome}}"])
def test_wrapper_sem_nome_valido_preserva_chamada_apenas_com_email(
    monkeypatch, client, nome
):
    chamadas_kit = []
    persistido = {}
    _instalar_supabase(monkeypatch, persistido)
    monkeypatch.setattr(
        main,
        "adicionar_lead_convertkit",
        lambda *args: chamadas_kit.append(args),
    )
    payload = {
        "manychat_id": "abc123",
        "email": "lead@example.com",
    }
    if nome is not None:
        payload["nome"] = nome

    resposta = client.post("/webhook", json=payload)

    assert chamadas_kit == [("lead@example.com",)]
    assert resposta.json()["status"] == "sucesso"
    assert resposta.json()["convertkit_lead_agendado"] is True
