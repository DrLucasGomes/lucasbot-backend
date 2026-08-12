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


def test_convertkit_lead_sem_api_key_nao_faz_chamada(monkeypatch):
    chamadas = []
    monkeypatch.delenv("CONVERTKIT_API_KEY", raising=False)
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: chamadas.append((a, k)))

    main.adicionar_lead_convertkit("lead@example.com")
    assert chamadas == []


def test_convertkit_lead_sem_tag_nao_faz_chamada(monkeypatch):
    chamadas = []
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key")
    monkeypatch.delenv("TAG_LEAD_ID", raising=False)
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: chamadas.append((a, k)))

    main.adicionar_lead_convertkit("lead@example.com")
    assert chamadas == []


def test_convertkit_lead_email_invalido_nao_faz_chamada(monkeypatch):
    chamadas = []
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: chamadas.append((a, k)))

    main.adicionar_lead_convertkit("{{email}}")
    assert chamadas == []


def test_convertkit_abandono_falha_de_rede_nao_derruba_funcao(monkeypatch):
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key")
    monkeypatch.setenv("TAG_ABANDONO_ID", "10")

    def falha(*args, **kwargs):
        raise RuntimeError("convertkit offline")

    monkeypatch.setattr(main.requests, "post", falha)
    main.gerenciar_tags_convertkit("lead@example.com", "abandoned")


def test_convertkit_pago_adiciona_comprador_e_remove_abandono(monkeypatch):
    chamadas = []
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key")
    monkeypatch.setenv("TAG_COMPRADOR_ID", "20")
    monkeypatch.setenv("TAG_ABANDONO_ID", "10")

    def fake_post(url, json=None, timeout=None, **kwargs):
        chamadas.append((url, json))
        return FakeResponse(200, {"ok": True}, "ok")

    monkeypatch.setattr(main.requests, "post", fake_post)
    main.gerenciar_tags_convertkit("buyer@example.com", "paid")

    assert any("/tags/20/subscribe" in url for url, _ in chamadas)
    assert any("/tags/10/unsubscribe" in url for url, _ in chamadas)


def test_manychat_headers_refletem_token_atual(monkeypatch):
    monkeypatch.setenv("MANYCHAT_TOKEN", "token-novo")
    headers = main.obter_headers_manychat()
    assert headers["Authorization"] == "Bearer token-novo"


def test_supabase_headers_refletem_chave_atual(monkeypatch):
    monkeypatch.setenv("SUPABASE_KEY", "supabase-nova")
    headers = main.obter_headers_supabase(prefer="return=representation")
    assert headers["apikey"] == "supabase-nova"
    assert headers["Authorization"] == "Bearer supabase-nova"
    assert headers["Prefer"] == "return=representation"


def test_webhook_supabase_204_sem_json_eh_sucesso(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeResponse(204, ValueError("sem corpo"), "")

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "adicionar_lead_convertkit", lambda email: None)

    resposta = client.post("/webhook", json={"manychat_id": "123", "email": "lead@example.com"})
    dados = resposta.json()
    assert dados["status"] == "sucesso"
    assert dados["code"] == 204


def test_kiwify_manychat_tag_500_preserva_compra_salva(monkeypatch):
    chamadas = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            return FakeResponse(200, [])
        return FakeResponse(200, {})

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        chamadas.append((url, json))
        if "leads_vigor" in url:
            return FakeResponse(200, [{"id": 1, **(json or {})}])
        if "addTagByName" in url:
            return FakeResponse(500, {"error": "manychat offline"}, "erro")
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "order": {
            "order_status": "paid",
            "Product": {"product_name": "Protocolo Vigor 360"},
            "Customer": {"full_name": "Buyer", "email": "buyer@example.com"},
            "custom_variables": {"manychat_id": "999"},
        }
    }

    dados = client.post("/kiwify", json=payload).json()
    assert dados["status"] == "sucesso_id_direto"
    assert dados["supabase_code"] == 200
    assert dados["manychat_code"] == 500


def test_kiwify_manychat_excecao_na_tag_nao_apaga_compra(monkeypatch):
    posts_supabase = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            return FakeResponse(200, [])
        return FakeResponse(200, {})

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            posts_supabase.append(json)
            return FakeResponse(200, [{"id": 1, **(json or {})}])
        if "addTagByName" in url:
            raise RuntimeError("manychat caiu")
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)
    monkeypatch.delenv("MANYCHAT_TOKEN", raising=False)

    payload = {
        "order": {
            "order_status": "paid",
            "Product": {"product_name": "Protocolo Vigor 360"},
            "Customer": {"full_name": "Buyer", "email": "buyer2@example.com"},
            "custom_variables": {"manychat_id": "998"},
        }
    }

    dados = client.post("/kiwify", json=payload).json()
    assert posts_supabase[0]["status_pagamento"] == "paid"
    assert dados["status"] == "comprador_salvo_mas_nao_encontrado_no_manychat"


def test_kiwify_payload_com_order_e_cart_prioriza_order(monkeypatch):
    enviados = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            return FakeResponse(200, [])
        return FakeResponse(200, {})

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            enviados.append(json)
            return FakeResponse(200, [{"id": 1, **(json or {})}])
        if "addTagByName" in url:
            return FakeResponse(200, {"status": "ok"})
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "order": {
            "order_status": "paid",
            "Product": {"product_name": "Produto Pago"},
            "Customer": {"email": "order@example.com"},
            "custom_variables": {"manychat_id": "701"},
        },
        "cart": {
            "status": "abandoned",
            "email": "cart@example.com",
            "product_name": "Produto Carrinho",
            "custom_variables": {"manychat_id": "702"},
        },
    }

    dados = client.post("/kiwify", json=payload).json()
    assert enviados[0]["email"] == "order@example.com"
    assert enviados[0]["status_pagamento"] == "paid"
    assert enviados[0]["produto"] == "Produto Pago"
    assert dados["manychat_id_usado"] == "701"
