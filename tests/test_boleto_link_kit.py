import pytest

import pix_recovery


ORDER_ID = "e85eab89-b17a-4cb3-9aa1-a3f874f84e9d"
BOLETO_LINK = "https://api.starkbank.com/v2/boleto/6139797850554368/pdf"


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


def payload_boleto():
    return {
        "order": {
            "order_id": ORDER_ID,
            "webhook_event_type": "billet_created",
            "payment_method": "boleto",
            "order_status": "waiting_payment",
            "boleto_URL": "https://webhook.example.invalid/nao-confiar.pdf",
            "boleto_expiry_date": "28/08/2026",
            "Customer": {
                "email": "boleto@example.com",
                "first_name": "Eric",
            },
        }
    }


def test_confirmacao_server_to_server_retorna_boleto_url_oficial(monkeypatch):
    monkeypatch.setenv("KIWIFY_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(pix_recovery, "_obter_oauth_token_kiwify", lambda: "token")
    monkeypatch.setattr(
        pix_recovery.requests,
        "get",
        lambda *a, **k: FakeResponse(
            200,
            {
                "id": ORDER_ID,
                "status": "waiting_payment",
                "payment_method": "boleto",
                "boleto_url": BOLETO_LINK,
                "customer": {
                    "email": "oficial@example.com",
                    "name": "Eric Vargas",
                },
            },
        ),
    )

    venda = pix_recovery.confirmar_venda_kiwify(
        ORDER_ID,
        {"waiting_payment"},
        payment_method_esperado="boleto",
    )

    assert venda["boleto_url"] == BOLETO_LINK
    assert venda["email"] == "oficial@example.com"
    assert venda["first_name"] == "Eric"


def test_subscribe_boleto_envia_link_em_custom_field_no_mesmo_post(monkeypatch):
    posts = []
    monkeypatch.setenv("TAG_BOLETO_ID", "tag-boleto")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda url, **kwargs: posts.append((url, kwargs)) or FakeResponse(201),
    )

    assert pix_recovery._alterar_tag_boleto_kit(
        "oficial@example.com",
        "subscribe",
        "Eric",
        BOLETO_LINK,
    ) is True

    assert posts == [
        (
            "https://api.convertkit.com/v3/tags/tag-boleto/subscribe",
            {
                "json": {
                    "api_secret": "secret",
                    "email": "oficial@example.com",
                    "first_name": "Eric",
                    "fields": {"boleto_link": BOLETO_LINK},
                },
                "timeout": 5,
            },
        )
    ]


def test_unsubscribe_boleto_nao_envia_custom_field(monkeypatch):
    posts = []
    monkeypatch.setenv("TAG_BOLETO_ID", "tag-boleto")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda url, **kwargs: posts.append((url, kwargs)) or FakeResponse(204),
    )

    assert pix_recovery._alterar_tag_boleto_kit(
        "oficial@example.com",
        "unsubscribe",
        "Eric",
        BOLETO_LINK,
    ) is True

    assert posts[0][1]["json"] == {
        "api_secret": "secret",
        "email": "oficial@example.com",
    }


@pytest.mark.parametrize(
    "valor",
    [
        None,
        "",
        "http://example.com/boleto.pdf",
        "javascript:alert(1)",
        "/boleto/123",
        "not-a-url",
    ],
)
def test_boleto_link_aceita_apenas_https_absoluto(valor):
    assert pix_recovery._normalizar_boleto_link(valor) == ""


def test_processamento_usa_link_confirmado_e_ignora_url_do_webhook(monkeypatch):
    chamadas_kit = []
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_venda_kiwify",
        lambda *a, **k: {
            "id": ORDER_ID,
            "status": "waiting_payment",
            "payment_method": "boleto",
            "email": "oficial@example.com",
            "first_name": "Eric",
            "boleto_url": BOLETO_LINK,
        },
    )
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *a, **k: True)
    monkeypatch.setattr(pix_recovery, "transicionar", lambda *a, **k: True)
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_boleto_kit",
        lambda *args: chamadas_kit.append(args) or True,
    )

    assert pix_recovery.processar_boleto_criado(payload_boleto()) is True
    assert chamadas_kit == [
        ("oficial@example.com", "subscribe", "Eric", BOLETO_LINK)
    ]


def test_sem_link_confirmado_ou_webhook_nao_inicia_ledger_nem_sequence(monkeypatch):
    efeitos = []
    payload = payload_boleto()
    payload["order"]["boleto_URL"] = ""
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_venda_kiwify",
        lambda *a, **k: {
            "id": ORDER_ID,
            "status": "waiting_payment",
            "payment_method": "boleto",
            "email": "oficial@example.com",
            "first_name": "Eric",
        },
    )
    monkeypatch.setattr(
        pix_recovery,
        "adquirir_processamento",
        lambda *a, **k: efeitos.append("ledger") or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_boleto_kit",
        lambda *a, **k: efeitos.append("kit") or True,
    )

    assert pix_recovery.processar_boleto_criado(payload) is False
    assert efeitos == []
