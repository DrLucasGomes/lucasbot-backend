import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main

client = TestClient(main.app)


class FakeResponse:
    def __init__(self, status_code=201, data=None, text="ok"):
        self.status_code = status_code
        self._data = [] if data is None else data
        self.text = text

    def json(self):
        return self._data


def test_webhook_sem_autenticacao_consegue_chegar_ao_supabase(monkeypatch):
    """Documenta a exposicao atual: qualquer POST bem-formado chega ao caminho de escrita."""
    escritas = []

    def fake_post(url, json=None, **kwargs):
        escritas.append((url, json))
        return FakeResponse(201, [json])

    monkeypatch.setattr(main.requests, "post", fake_post)

    resposta = client.post(
        "/webhook",
        json={"manychat_id": "atacante-123", "email": "fake@example.com", "score": 99},
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "sucesso"
    assert len(escritas) >= 1
    assert escritas[0][1]["manychat_id"] == "atacante-123"


def test_webhook_header_inventado_nao_e_validado(monkeypatch):
    escritas = []

    def fake_post(url, json=None, **kwargs):
        escritas.append(json)
        return FakeResponse(201, [json])

    monkeypatch.setattr(main.requests, "post", fake_post)

    resposta = client.post(
        "/webhook",
        headers={"X-Webhook-Secret": "qualquer-coisa"},
        json={"manychat_id": "fake-header", "idade": 45},
    )

    assert resposta.json()["status"] == "sucesso"
    assert escritas


def test_kiwify_sem_assinatura_e_processada(monkeypatch):
    """Documenta que /kiwify nao exige assinatura/segredo antes de processar."""
    posts = []

    def fake_get(url, params=None, **kwargs):
        # Simula lead existente para que o evento forjado alcance a atualizacao.
        if params and "manychat_id" in params:
            return FakeResponse(200, [{"id": 1, "manychat_id": "777", "email": "buyer@example.com", "status_pagamento": "abandoned"}])
        return FakeResponse(200, [])

    def fake_post(url, json=None, **kwargs):
        posts.append((url, json))
        return FakeResponse(201, [json] if json else [])

    def fake_patch(url, json=None, **kwargs):
        posts.append((url, json))
        return FakeResponse(200, [json])

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main.requests, "patch", fake_patch)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "order_status": "paid",
        "Customer": {"email": "buyer@example.com", "mobile": "+5549999999999"},
        "Product": {"product_name": "Produto Falso"},
        "src": "mc_777",
    }

    resposta = client.post("/kiwify", json=payload)

    assert resposta.status_code == 200
    # O ponto de seguranca e: a requisicao sem credencial nao foi rejeitada com 401/403.
    assert resposta.status_code not in (401, 403)


def test_endpoints_nao_exigem_authorization_header(monkeypatch):
    def fake_post(url, json=None, **kwargs):
        return FakeResponse(201, [json] if json else [])

    monkeypatch.setattr(main.requests, "post", fake_post)

    resposta = client.post("/webhook", json={"manychat_id": "sem-auth"})
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "sucesso"
