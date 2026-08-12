import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


client = TestClient(main.app)


def test_webhook_body_nao_json_retorna_erro_critico():
    resposta = client.post("/webhook", content="nao-json", headers={"content-type": "application/json"})
    dados = resposta.json()
    assert dados["status"] == "erro_critico"


def test_kiwify_body_nao_json_retorna_erro_critico():
    resposta = client.post("/kiwify", content="nao-json", headers={"content-type": "application/json"})
    dados = resposta.json()
    assert dados["status"] == "erro_critico"


def test_webhook_lista_em_vez_de_objeto_retorna_erro_critico():
    resposta = client.post("/webhook", json=[{"manychat_id": "123"}])
    assert resposta.json()["status"] == "erro_critico"


def test_kiwify_lista_em_vez_de_objeto_retorna_erro_critico():
    resposta = client.post("/kiwify", json=[{"email": "x@example.com"}])
    assert resposta.json()["status"] == "erro_critico"


def test_webhook_muitos_campos_desconhecidos_nao_vazam_para_supabase(monkeypatch):
    capturado = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        capturado["json"] = json
        return FakeResponse(201, [json])

    monkeypatch.setattr(main.requests, "post", fake_post)

    payload = {"manychat_id": "123", "email": "ok@example.com"}
    for i in range(100):
        payload[f"campo_invasor_{i}"] = f"valor-{i}"

    resposta = client.post("/webhook", json=payload)
    assert resposta.json()["status"] == "sucesso"
    assert capturado["json"] == {"manychat_id": "123", "email": "ok@example.com"}


def test_kiwify_status_desconhecido_nao_aplica_tag_de_compra(monkeypatch):
    posts = []

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        posts.append(url)
        if "leads_vigor" in url:
            return FakeResponse(200, [{"id": 1, **(json or {})}])
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "order": {
            "order_status": "pending",
            "Product": {"product_name": "Protocolo Vigor 360"},
            "Customer": {"email": "pending@example.com"},
            "custom_variables": {"manychat_id": "123"},
        }
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()
    assert dados["status"] == "processado"
    assert dados["status_pagamento"] == "pending"
    assert not any("addTagByName" in url for url in posts)


def test_kiwify_email_com_espacos_e_normalizado_no_payload_supabase(monkeypatch):
    capturado = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            capturado["json"] = json
            return FakeResponse(200, [json])
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "cart": {
            "status": "abandoned",
            "email": "  lead@example.com  ",
            "product_name": "Protocolo Vigor 360",
            "custom_variables": {"manychat_id": "321"},
        }
    }

    resposta = client.post("/kiwify", json=payload)
    assert resposta.json()["status"] == "processado"
    assert capturado["json"]["email"] == "lead@example.com"


def test_kiwify_src_manychat_sem_custom_variables_usa_id_da_url(monkeypatch):
    capturado = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            capturado["json"] = json
            return FakeResponse(200, [json])
        if "addTagByName" in url:
            return FakeResponse(200, {"status": "success"})
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "order": {
            "order_status": "paid",
            "Product": {"product_name": "Protocolo Vigor 360"},
            "Customer": {"email": "src@example.com"},
        },
        "payment_url": "https://pay.kiwify.com.br/x?src=mc_456789&utm_source=manychat",
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()
    assert dados["status"] == "sucesso_id_direto"
    assert dados["manychat_id_usado"] == "456789"
    assert capturado["json"]["manychat_id"] == "456789"


def test_kiwify_custom_variables_invalido_cai_para_src(monkeypatch):
    capturado = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            capturado["json"] = json
            return FakeResponse(200, [json])
        if "addTagByName" in url:
            return FakeResponse(200, {"status": "success"})
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "order": {
            "order_status": "paid",
            "Product": {"product_name": "Protocolo Vigor 360"},
            "Customer": {"email": "fallback@example.com"},
            "custom_variables": {"manychat_id": "{{manychat_id}}"},
        },
        "payment_url": "https://pay.kiwify.com.br/x?src=mc_999888",
    }

    resposta = client.post("/kiwify", json=payload)
    assert resposta.json()["manychat_id_usado"] == "999888"
    assert capturado["json"]["manychat_id"] == "999888"


def test_kiwify_payload_aninhado_em_data_recupera_cliente(monkeypatch):
    posts = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        return FakeResponse(200, [])

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        posts.append((url, json))
        if "leads_vigor" in url:
            return FakeResponse(201, [{"id": 1, **(json or {})}])
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "data": {
            "Customer": {"email": "nested@example.com", "full_name": "Nested User"},
            "Product": {"product_name": "Protocolo Vigor 360"},
            "status": "abandoned",
        }
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()
    assert dados["status"] == "processado"
    supabase_payload = next(json for url, json in posts if "leads_vigor" in url)
    assert supabase_payload["email"] == "nested@example.com"
    assert supabase_payload["nome"] == "Nested User"
    assert supabase_payload["produto"] == "Protocolo Vigor 360"
