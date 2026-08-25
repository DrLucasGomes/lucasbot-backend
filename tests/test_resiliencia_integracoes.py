import sys
from pathlib import Path

import pytest
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


def test_convertkit_lead_sem_api_secret_nao_faz_chamada(monkeypatch):
    chamadas = []
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key")
    monkeypatch.delenv("CONVERTKIT_API_SECRET", raising=False)
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: chamadas.append((a, k)))

    main.adicionar_lead_convertkit("lead@example.com")
    assert chamadas == []


def test_convertkit_lead_sem_tag_nao_faz_chamada(monkeypatch):
    chamadas = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.delenv("TAG_LEAD_ID", raising=False)
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: chamadas.append((a, k)))

    main.adicionar_lead_convertkit("lead@example.com")
    assert chamadas == []


def test_convertkit_lead_email_invalido_nao_faz_chamada(monkeypatch):
    chamadas = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: chamadas.append((a, k)))

    main.adicionar_lead_convertkit("{{email}}")
    assert chamadas == []


def test_convertkit_lead_com_nome_atualiza_subscriber_via_put(monkeypatch):
    posts = []
    puts = []
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(
        main.requests,
        "post",
        lambda *args, **kwargs: posts.append(kwargs["json"])
        or FakeResponse(200, {"subscription": {"subscriber": {"id": 789}}}),
    )
    monkeypatch.setattr(
        main.requests,
        "put",
        lambda url, **kwargs: puts.append((url, kwargs)) or FakeResponse(200),
    )

    main.adicionar_lead_convertkit("lead@example.com", "Lucas Felipe Gomes")

    assert posts == [{"api_secret": "secret", "email": "lead@example.com"}]
    assert puts == [
        (
            "https://api.convertkit.com/v3/subscribers/789",
            {
                "json": {"api_secret": "secret", "first_name": "Lucas"},
                "timeout": 5,
            },
        )
    ]
    assert "email" not in puts[0][1]["json"]


def test_convertkit_lead_instrumenta_estagios_sem_pii(monkeypatch, capsys):
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "segredo-instrumentacao")
    monkeypatch.setenv("TAG_LEAD_ID", "tag-instrumentacao")
    monkeypatch.setattr(
        main.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(
            200, {"subscription": {"subscriber": {"id": 789}}}
        ),
    )
    monkeypatch.setattr(main.requests, "put", lambda *a, **k: FakeResponse(200))

    main.adicionar_lead_convertkit("instrumentacao@example.com", "Lucas Gomes")
    logs = capsys.readouterr().out

    for esperado in (
        "stage=kit_helper_entered first_name_present=True",
        "stage=kit_subscribe_completed success=True",
        "stage=subscriber_id_valid value=True",
        "stage=first_name_put_attempted",
        "stage=first_name_put_completed success=True",
    ):
        assert esperado in logs
    for pii in (
        "instrumentacao@example.com",
        "Lucas",
        "Gomes",
        "789",
        "segredo-instrumentacao",
        "tag-instrumentacao",
    ):
        assert pii not in logs


@pytest.mark.parametrize("nome", [None, "", "   ", {"nome": "Lucas"}])
def test_convertkit_lead_nome_ausente_vazio_ou_invalido_preserva_payload(
    monkeypatch, nome
):
    enviados = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(
        main.requests,
        "post",
        lambda *args, **kwargs: enviados.append(kwargs["json"])
        or FakeResponse(200, {}, "ok"),
    )

    main.adicionar_lead_convertkit("lead@example.com", nome)

    assert enviados == [{"api_secret": "secret", "email": "lead@example.com"}]


def test_convertkit_lead_chamada_antiga_sem_nome_continua_funcionando(monkeypatch):
    enviados = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(
        main.requests,
        "post",
        lambda *args, **kwargs: enviados.append(kwargs["json"])
        or FakeResponse(200, {}, "ok"),
    )

    main.adicionar_lead_convertkit("lead@example.com")

    assert enviados == [{"api_secret": "secret", "email": "lead@example.com"}]


@pytest.mark.parametrize("json_data", [{}, ValueError("json invalido")])
def test_convertkit_lead_sem_subscriber_id_preserva_sucesso_e_nao_faz_put(
    monkeypatch, json_data
):
    puts = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(
        main.requests, "post", lambda *a, **k: FakeResponse(200, json_data)
    )
    monkeypatch.setattr(main.requests, "put", lambda *a, **k: puts.append((a, k)))

    main.adicionar_lead_convertkit("lead@example.com", "Lucas Gomes")

    assert puts == []


@pytest.mark.parametrize("status_code", [400, 500])
def test_convertkit_lead_falha_http_no_put_nao_quebra_manychat(monkeypatch, status_code):
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(
        main.requests,
        "post",
        lambda *a, **k: FakeResponse(
            200, {"subscription": {"subscriber": {"id": 789}}}
        ),
    )
    monkeypatch.setattr(
        main.requests, "put", lambda *a, **k: FakeResponse(status_code)
    )

    assert main.adicionar_lead_convertkit("lead@example.com", "Lucas") is None


@pytest.mark.parametrize("subscriber_id", [None, "", "   ", 0, -1, True, []])
def test_convertkit_lead_subscriber_id_invalido_nao_faz_put(
    monkeypatch, subscriber_id
):
    puts = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(
        main.requests,
        "post",
        lambda *a, **k: FakeResponse(
            200, {"subscription": {"subscriber": {"id": subscriber_id}}}
        ),
    )
    monkeypatch.setattr(main.requests, "put", lambda *a, **k: puts.append((a, k)))

    main.adicionar_lead_convertkit("lead@example.com", "Lucas")

    assert puts == []


def test_convertkit_lead_falha_put_loga_sem_pii(monkeypatch, capsys):
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "segredo-ultrassecreto")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(
        main.requests,
        "post",
        lambda *a, **k: FakeResponse(
            200, {"subscription": {"subscriber": {"id": 987654}}}
        ),
    )

    def put_falha(*args, **kwargs):
        raise RuntimeError("Lucas lead@example.com response-body-sensivel")

    monkeypatch.setattr(main.requests, "put", put_falha)
    main.adicionar_lead_convertkit("lead@example.com", "Lucas")
    logs = capsys.readouterr().out

    assert "operation=update_first_name" in logs
    assert "RuntimeError" in logs
    for pii in (
        "Lucas",
        "lead@example.com",
        "987654",
        "segredo-ultrassecreto",
        "response-body-sensivel",
    ):
        assert pii not in logs


def test_convertkit_lead_logs_sao_sanitizados(monkeypatch, capsys):
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(
        main.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(
            422,
            {
                "subscription": {
                    "subscriber": {"id": 456, "first_name": "Lucas"}
                }
            },
            "response-body-com-dado-sensivel",
        ),
    )

    main.adicionar_lead_convertkit("lead@example.com", "Lucas Gomes")
    logs = capsys.readouterr().out

    assert "operation=subscribe" in logs
    assert "status_http=422" in logs
    assert "json_valid=True" in logs
    assert "subscriber_id_present=True" in logs
    assert "first_name_present=True" in logs
    assert "lead@example.com" not in logs
    assert "Lucas" not in logs
    assert "456" not in logs
    assert "response-body-com-dado-sensivel" not in logs


def test_convertkit_lead_excecao_logada_apenas_pelo_tipo(monkeypatch, capsys):
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_LEAD_ID", "123")

    def falha(*args, **kwargs):
        raise RuntimeError("erro-com-dado-sensivel")

    monkeypatch.setattr(main.requests, "post", falha)
    main.adicionar_lead_convertkit("lead@example.com", "Lucas Gomes")
    logs = capsys.readouterr().out

    assert "RuntimeError" in logs
    assert "lead@example.com" not in logs
    assert "Lucas" not in logs
    assert "erro-com-dado-sensivel" not in logs


def test_falha_convertkit_lead_nao_quebra_resposta_webhook(monkeypatch):
    def fake_post(url, *args, **kwargs):
        if "leads_vigor" in url:
            return FakeResponse(201, [{"id": 1}])
        raise RuntimeError("kit offline")

    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_LEAD_ID", "123")
    monkeypatch.setattr(main.requests, "post", fake_post)

    resposta = client.post(
        "/webhook",
        json={
            "manychat_id": "123",
            "email": "lead@example.com",
            "nome": "Lucas Gomes",
        },
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "sucesso"


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
