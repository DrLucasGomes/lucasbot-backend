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


def test_kiwify_abandono_por_manychat_src_faz_upsert(monkeypatch):
    posts = []
    tarefas = []

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        posts.append((url, json))
        if "leads_vigor" in url:
            return FakeResponse(200, [{"id": 1, **json}])
        return FakeResponse(200, {"status": "success"})

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda email, status: tarefas.append((email, status)))

    payload = {
        "cart": {
            "status": "abandoned",
            "email": "abandono@example.com",
            "name": "Teste Abandono",
            "phone": "+55 (49) 99999-1111",
            "product_name": "Protocolo Vigor 360",
        },
        "checkout_url": "https://pay.kiwify.com.br/MQqd0hF?src=mc_123456&utm_source=manychat&utm_medium=whatsapp&utm_campaign=vigor360",
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()

    assert dados["status"] == "processado"
    assert dados["status_pagamento"] == "abandoned"
    assert dados["supabase_acao"] == "upsert_por_manychat_id"
    assert any("on_conflict=manychat_id" in url for url, _ in posts)
    supabase_payload = next(json for url, json in posts if "leads_vigor" in url)
    assert supabase_payload["manychat_id"] == "123456"
    assert supabase_payload["telefone"] == "5549999991111"
    assert supabase_payload["origem_compra"] == "manychat"
    assert supabase_payload["checkout_utm_campaign"] == "vigor360"
    assert tarefas == [("abandono@example.com", "abandoned")]


def test_kiwify_compra_manychat_aplica_tag_comprador(monkeypatch):
    posts = []
    tarefas = []

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        posts.append((url, json))
        if "leads_vigor" in url:
            return FakeResponse(200, [{"id": 1, **json}])
        if "addTagByName" in url:
            return FakeResponse(200, {"status": "success"})
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda email, status: tarefas.append((email, status)))

    payload = {
        "order": {
            "order_status": "paid",
            "Product": {"product_name": "Protocolo Vigor 360"},
            "Customer": {
                "full_name": "Comprador Teste",
                "email": "comprador@example.com",
                "mobile": "+55 49 99999-2222",
            },
        },
        "payment_url": "https://pay.kiwify.com.br/x?src=mc_987654&utm_source=manychat&utm_campaign=vigor360",
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()

    assert dados["status"] == "sucesso_id_direto"
    assert dados["manychat_id_usado"] == "987654"
    assert dados["origem_compra"] == "manychat"
    assert dados["manychat_code"] == 200
    tag_payload = next(json for url, json in posts if "addTagByName" in url)
    assert tag_payload == {
        "subscriber_id": 987654,
        "tag_name": "comprou-vigor360",
    }
    assert tarefas == [("comprador@example.com", "paid")]


def test_kiwify_facebook_direto_insere_novo_lead(monkeypatch):
    posts = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        return FakeResponse(200, [])

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        posts.append((url, json))
        if "leads_vigor" in url:
            return FakeResponse(201, [{"id": 77, **json}])
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "cart": {
            "status": "abandoned",
            "email": "facebook@example.com",
            "name": "Lead Facebook",
            "phone": "+55 48 98888-7777",
            "product_name": "Protocolo Vigor 360",
        },
        "checkout_link": "https://pay.kiwify.com.br/x?src=facebook_direto&utm_source=facebook&utm_campaign=vigor_fb",
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()

    assert dados["status"] == "processado"
    assert dados["supabase_acao"] == "insert_novo_lead"
    supabase_payload = next(json for url, json in posts if "leads_vigor" in url)
    assert supabase_payload["origem_compra"] == "facebook_direto"
    assert supabase_payload["checkout_utm_source"] == "facebook"
    assert supabase_payload["checkout_utm_campaign"] == "vigor_fb"


def test_kiwify_sem_manychat_id_encontra_por_email_e_faz_patch(monkeypatch):
    patches = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        campo = next((k for k in ["telefone", "telefone_whatsapp", "telefone_checkout_kiwify", "email"] if k in (params or {})), None)
        if campo == "email":
            return FakeResponse(200, [{
                "id": 510,
                "email": "existente@example.com",
                "telefone": None,
                "telefone_whatsapp": None,
                "telefone_checkout_kiwify": None,
                "manychat_id": "2065543040",
            }])
        return FakeResponse(200, [])

    def fake_patch(url, params=None, json=None, headers=None, timeout=None, **kwargs):
        patches.append((url, params, json))
        return FakeResponse(200, [{"id": 510, **json}])

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "patch", fake_patch)
    monkeypatch.setattr(main.requests, "post", lambda *args, **kwargs: FakeResponse(200, {}))
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "cart": {
            "status": "abandoned",
            "email": "existente@example.com",
            "name": "Lead Existente",
            "product_name": "Protocolo Vigor 360",
        }
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()

    assert dados["status"] == "processado"
    assert dados["supabase_acao"] == "patch_por_telefone_whatsapp_checkout_ou_email"
    assert patches[0][1] == {"id": "eq.510"}


def test_kiwify_json_sem_contato_eh_ignorado(monkeypatch):
    monkeypatch.setattr(main.requests, "post", lambda *args, **kwargs: FakeResponse(200, {}))

    resposta = client.post("/kiwify", json={"evento": "qualquer", "data": {"x": 1}})
    dados = resposta.json()

    assert dados["status"] == "ignorado"
    assert dados["detalhe"] == "JSON sem dados de contato acessiveis"
    assert "tracking_detectado" in dados


def test_kiwify_tracking_em_url_aninhada(monkeypatch):
    posts = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        return FakeResponse(200, [])

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        posts.append((url, json))
        if "leads_vigor" in url:
            return FakeResponse(201, [{"id": 1, **json}])
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "cart": {
            "status": "abandoned",
            "email": "yt@example.com",
            "name": "Lead YT",
            "product_name": "Protocolo Vigor 360",
        },
        "data": {
            "links": {
                "checkout": "https://pay.kiwify.com.br/x?src=youtube_direto&utm_source=youtube&utm_medium=video&utm_campaign=yt_001"
            }
        },
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()

    assert dados["status"] == "processado"
    assert dados["supabase_acao"] == "insert_novo_lead"
    supabase_payload = next(json for url, json in posts if "leads_vigor" in url)
    assert supabase_payload["origem_compra"] == "youtube_direto"
    assert supabase_payload["checkout_utm_medium"] == "video"
    assert supabase_payload["checkout_utm_campaign"] == "yt_001"


def test_kiwify_supabase_erro_nao_quebra_processamento(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            return FakeResponse(500, {"message": "erro supabase"})
        return FakeResponse(200, {"status": "success"})

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "cart": {
            "status": "abandoned",
            "email": "erro@example.com",
            "name": "Erro",
            "product_name": "Protocolo Vigor 360",
            "custom_variables": {"manychat_id": "333"},
        }
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()

    assert dados["status"] == "processado"
    assert dados["supabase_acao"] == "upsert_por_manychat_id"
    assert dados["supabase_code"] == 500
    assert dados["supabase_resposta"]["message"] == "erro supabase"


def test_kiwify_excecao_de_rede_retorna_erro_critico(monkeypatch):
    def fake_post(*args, **kwargs):
        raise RuntimeError("rede indisponivel")

    monkeypatch.setattr(main.requests, "post", fake_post)

    payload = {
        "cart": {
            "status": "abandoned",
            "email": "rede@example.com",
            "name": "Rede",
            "product_name": "Protocolo Vigor 360",
            "custom_variables": {"manychat_id": "444"},
        }
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()

    assert dados["status"] == "erro_critico"
    assert "rede indisponivel" in dados["detalhe"]


def test_kiwify_order_com_custom_variables_tem_prioridade(monkeypatch):
    posts = []

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        posts.append((url, json))
        if "leads_vigor" in url:
            return FakeResponse(200, [{"id": 1, **json}])
        if "addTagByName" in url:
            return FakeResponse(200, {"status": "success"})
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)

    payload = {
        "order": {
            "order_status": "approved",
            "Product": {"product_name": "Protocolo Vigor 360"},
            "Customer": {
                "full_name": "Custom Var",
                "email": "custom@example.com",
                "mobile": "+55 49 90000-0000",
            },
            "custom_variables": {"manychat_id": "555"},
        },
        "payment_url": "https://pay.kiwify.com.br/x?src=mc_999&utm_source=manychat",
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()

    assert dados["status"] == "sucesso_id_direto"
    assert dados["manychat_id_usado"] == "555"
    supabase_payload = next(json for url, json in posts if "leads_vigor" in url)
    assert supabase_payload["manychat_id"] == "555"


def test_kiwify_compra_sem_manychat_salva_mesmo_sem_encontrar_no_manychat(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        return FakeResponse(200, [])

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            return FakeResponse(201, [{"id": 88, **json}])
        if "findByCustomField" in url:
            return FakeResponse(200, {"data": []})
        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "gerenciar_tags_convertkit", lambda *args, **kwargs: None)
    monkeypatch.setenv("MANYCHAT_TOKEN", "token-teste")

    payload = {
        "order": {
            "order_status": "paid",
            "Product": {"product_name": "Protocolo Vigor 360"},
            "Customer": {
                "full_name": "Direto",
                "email": "direto@example.com",
            },
        },
        "payment_url": "https://pay.kiwify.com.br/x?src=facebook_direto&utm_source=facebook",
    }

    resposta = client.post("/kiwify", json=payload)
    dados = resposta.json()

    assert dados["status"] == "comprador_salvo_mas_nao_encontrado_no_manychat"
    assert dados["supabase_acao"] == "insert_novo_lead"
    assert dados["origem_compra"] == "facebook_direto"
