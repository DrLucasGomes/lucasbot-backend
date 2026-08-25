import asyncio
import ast
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

import pix_recovery


CONFIRMAR_VENDA_KIWIFY_REAL = pix_recovery.confirmar_venda_kiwify


def payload_pix(**overrides):
    order = {
        "order_id": "46bc33eb-6e53-4b4d-a8f7-72757a84b4ef",
        "order_status": "waiting_payment",
        "payment_method": "pix",
        "webhook_event_type": "pix_created",
        "Customer": {"email": "teste@example.com"},
    }
    order.update(overrides)
    return {"order": order}


def payload_pix_plano(**overrides):
    return payload_pix(**overrides)["order"]


class FakeResponse:
    def __init__(self, status_code, payload=None, json_error=None):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeRequest:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.json_calls = 0
        self.query_params = {}
        self.headers = {}

    async def json(self):
        self.json_calls += 1
        if self.error:
            raise self.error
        return self.payload


@pytest.fixture(autouse=True)
def confirmar_venda_kiwify_por_padrao(monkeypatch):
    """Mantém os testes do ledger isolados; testes da API usam a função real salva."""
    def confirmar(order_id, statuses_aceitos, payment_method_esperado=None):
        status = "paid" if "paid" in statuses_aceitos else "waiting_payment"
        return {
            "id": order_id,
            "status": status,
            "payment_method": payment_method_esperado or "pix",
            "email": "teste@example.com",
        }

    monkeypatch.setattr(pix_recovery, "confirmar_venda_kiwify", confirmar)
    monkeypatch.setattr(pix_recovery, "enfileirar_job_pix", lambda *args: True)


def test_reconhece_contrato_real_pix_created():
    assert pix_recovery._evento_pix_criado(payload_pix()) is True


def test_waiting_payment_sozinho_nao_dispara_pix():
    assert pix_recovery._evento_pix_criado(payload_pix(webhook_event_type="order_created")) is False


def test_metodo_nao_pix_nao_dispara_pix():
    assert pix_recovery._evento_pix_criado(payload_pix(payment_method="boleto")) is False


def test_status_nao_waiting_payment_nao_dispara_pix():
    assert pix_recovery._evento_pix_criado(payload_pix(order_status="pending")) is False


def test_order_id_ausente_nao_dispara_pix():
    assert pix_recovery._evento_pix_criado(payload_pix(order_id="")) is False


def test_pagamento_aprovado_e_evento_terminal():
    assert pix_recovery._evento_pago(
        payload_pix(order_status="paid", webhook_event_type="order_approved")
    ) is True


def test_pix_valido_faz_transicoes_com_mesmo_attempt_token(monkeypatch):
    eventos = []
    monkeypatch.setattr(pix_recovery, "uuid4", lambda: "attempt-1")
    monkeypatch.setattr(
        pix_recovery,
        "adquirir_processamento",
        lambda order_id, email, token: eventos.append(("acquire", token)) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "transicionar",
        lambda order_id, token, origem, destino: eventos.append(
            ("transition", token, origem, destino)
        ) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda email, acao: eventos.append(("kit", acao, email)) or True,
    )

    pix_recovery.processar_pix_criado(payload_pix())

    assert ("acquire", "attempt-1") in eventos
    assert ("transition", "attempt-1", "processing", "subscribing") in eventos
    assert ("transition", "attempt-1", "subscribing", "completed") in eventos


def test_duplicata_nao_reaplica_subscribe(monkeypatch):
    chamadas = []
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: False)
    monkeypatch.setattr(pix_recovery, "reconciliar_cancelamento", lambda *args: False)
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda *args: chamadas.append(args) or True,
    )
    pix_recovery.processar_pix_criado(payload_pix())
    assert chamadas == []


def test_falha_do_kit_marca_failed_com_token(monkeypatch):
    transicoes = []
    monkeypatch.setattr(pix_recovery, "uuid4", lambda: "attempt-2")
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: True)
    monkeypatch.setattr(pix_recovery, "compensar_subscribe_concorrente", lambda *args: False)
    monkeypatch.setattr(
        pix_recovery,
        "transicionar",
        lambda order_id, token, origem, destino: transicoes.append(
            (token, origem, destino)
        ) or True,
    )
    monkeypatch.setattr(pix_recovery, "_alterar_tag_kit", lambda *args: False)

    pix_recovery.processar_pix_criado(payload_pix())

    assert ("attempt-2", "subscribing", "failed") in transicoes
    assert ("attempt-2", "subscribing", "completed") not in transicoes


def test_falha_exclusiva_do_first_name_conclui_pix_sem_compensacao(monkeypatch):
    transicoes = []
    compensacoes = []
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret-value")
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "transicionar",
        lambda order_id, token, origem, destino: transicoes.append(
            (origem, destino)
        ) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "compensar_subscribe_concorrente",
        lambda *args: compensacoes.append(args) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_venda_kiwify",
        lambda *args, **kwargs: {
            "id": args[0],
            "status": "waiting_payment",
            "payment_method": "pix",
            "email": "teste@example.com",
            "first_name": "Maria",
        },
    )
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda *a, **k: FakeResponse(
            200, {"subscription": {"subscriber": {"id": 123}}}
        ),
    )
    monkeypatch.setattr(
        pix_recovery.requests,
        "put",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timeout")),
    )

    assert pix_recovery.processar_pix_criado(payload_pix()) is True
    assert transicoes == [
        ("processing", "subscribing"),
        ("subscribing", "completed"),
    ]
    assert compensacoes == []


def test_paid_antes_pix_impede_subscribe(monkeypatch):
    eventos = []
    monkeypatch.setattr(pix_recovery, "persistir_cancelamento", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento",
        lambda *args: eventos.append("unsubscribe") or True,
    )
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: False)

    pago = payload_pix(order_status="paid", webhook_event_type="order_approved")
    pix_recovery.cancelar_pix_por_pagamento(pago)
    pix_recovery.processar_pix_criado(payload_pix())

    assert eventos == ["unsubscribe", "unsubscribe"]


def test_subscribe_tardio_reabre_cancelled_antes_de_compensar(monkeypatch):
    eventos = []
    monkeypatch.setattr(pix_recovery, "uuid4", lambda: "attempt-race")
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: True)

    def transicao(order_id, token, origem, destino):
        if (origem, destino) == ("processing", "subscribing"):
            return True
        if (origem, destino) == ("subscribing", "completed"):
            return False
        return True

    monkeypatch.setattr(pix_recovery, "transicionar", transicao)
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda email, acao: eventos.append(acao) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "reabrir_cancelamento",
        lambda order_id, token: eventos.append(("reopen", token)) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento",
        lambda *args: eventos.append("compensate-unsubscribe") or True,
    )

    pix_recovery.processar_pix_criado(payload_pix())

    assert eventos == [
        "subscribe",
        ("reopen", "attempt-race"),
        "compensate-unsubscribe",
    ]


def test_worker_velho_sem_token_atual_ainda_tenta_reconciliar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(pix_recovery, "reabrir_cancelamento", lambda *args: False)
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento",
        lambda *args: chamadas.append("reconcile") or True,
    )

    assert pix_recovery.compensar_subscribe_concorrente(
        "order-1", "x@example.com", "token-velho"
    ) is True
    assert chamadas == ["reconcile"]


def test_timeout_ambiguo_tenta_compensacao(monkeypatch):
    eventos = []
    monkeypatch.setattr(pix_recovery, "uuid4", lambda: "attempt-timeout")
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "transicionar",
        lambda order_id, token, origem, destino: (origem, destino)
        == ("processing", "subscribing"),
    )

    def kit(email, acao):
        eventos.append(acao)
        raise TimeoutError("resultado remoto ambiguo")

    monkeypatch.setattr(pix_recovery, "_alterar_tag_kit", kit)
    monkeypatch.setattr(
        pix_recovery,
        "compensar_subscribe_concorrente",
        lambda *args: eventos.append("compensate") or True,
    )

    pix_recovery.processar_pix_criado(payload_pix())

    assert eventos == ["subscribe", "compensate"]


def test_pagamento_persiste_pending_antes_de_reconciliar(monkeypatch):
    eventos = []
    monkeypatch.setattr(
        pix_recovery,
        "persistir_cancelamento",
        lambda order_id, email: eventos.append("pending") or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento",
        lambda *args: eventos.append("unsubscribe") or True,
    )

    pix_recovery.cancelar_pix_por_pagamento(
        payload_pix(order_status="paid", webhook_event_type="order_approved")
    )
    assert eventos == ["pending", "unsubscribe"]


def test_sem_subscribe_previo_pode_confirmar_cancelled(monkeypatch):
    eventos = []
    monkeypatch.setattr(
        pix_recovery,
        "buscar_ledger",
        lambda order_id: {
            "email": "ledger@example.com",
            "status": "cancelled_pending_unsubscribe",
            "subscribe_attempted": False,
        },
    )
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda email, acao: eventos.append((acao, email)) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_cancelamento",
        lambda order_id: eventos.append(("confirm", order_id)) or True,
    )

    assert pix_recovery.reconciliar_cancelamento("order-1") is True
    assert eventos == [
        ("unsubscribe", "ledger@example.com"),
        ("confirm", "order-1"),
    ]


def test_qualquer_subscribe_previo_mantem_pending_apos_unsubscribe(monkeypatch):
    confirmacoes = []
    monkeypatch.setattr(
        pix_recovery,
        "buscar_ledger",
        lambda order_id: {
            "email": "ledger@example.com",
            "status": "cancelled_pending_unsubscribe",
            "subscribe_attempted": True,
        },
    )
    monkeypatch.setattr(pix_recovery, "_alterar_tag_kit", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_cancelamento",
        lambda order_id: confirmacoes.append(order_id) or True,
    )

    assert pix_recovery.reconciliar_cancelamento("order-1") is True
    assert confirmacoes == []


def test_falha_unsubscribe_mantem_pending(monkeypatch):
    confirmacoes = []
    monkeypatch.setattr(
        pix_recovery,
        "buscar_ledger",
        lambda order_id: {
            "email": "ledger@example.com",
            "status": "cancelled_pending_unsubscribe",
            "subscribe_attempted": True,
        },
    )
    monkeypatch.setattr(pix_recovery, "_alterar_tag_kit", lambda *args: False)
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_cancelamento",
        lambda order_id: confirmacoes.append(order_id) or True,
    )

    assert pix_recovery.reconciliar_cancelamento("order-1") is False
    assert confirmacoes == []


def test_cancelled_confirmado_nao_chama_kit(monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        pix_recovery,
        "buscar_ledger",
        lambda order_id: {
            "email": "x@example.com",
            "status": "cancelled",
            "subscribe_attempted": False,
        },
    )
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda *args: chamadas.append(args) or True,
    )

    assert pix_recovery.reconciliar_cancelamento("order-1") is True
    assert chamadas == []


def test_pagamento_sem_email_reconcilia_ledger(monkeypatch):
    eventos = []
    monkeypatch.setattr(pix_recovery, "persistir_cancelamento", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento",
        lambda order_id, email="": eventos.append((order_id, email)) or True,
    )

    pago = payload_pix(
        order_status="paid",
        webhook_event_type="order_approved",
        Customer={},
    )
    pix_recovery.cancelar_pix_por_pagamento(pago)

    assert eventos == [
        ("46bc33eb-6e53-4b4d-a8f7-72757a84b4ef", "teste@example.com")
    ]


def test_pix_created_plano_e_email_do_customer():
    payload = payload_pix_plano()

    assert pix_recovery._evento_pix_criado(payload) is True
    assert pix_recovery._dados_pix(payload) == {
        "order_id": "46bc33eb-6e53-4b4d-a8f7-72757a84b4ef",
        "email": "teste@example.com",
    }


def test_order_approved_plano_e_pago():
    payload = payload_pix_plano(
        order_status="paid", webhook_event_type="order_approved"
    )

    assert pix_recovery._evento_pago(payload) is True


def test_payload_envelopado_continua_suportado():
    payload = payload_pix()

    assert pix_recovery._evento_pix_criado(payload) is True
    assert pix_recovery._dados_pix(payload)["email"] == "teste@example.com"


def test_wrapper_json_invalido_preserva_handler_original(monkeypatch):
    request = FakeRequest(error=ValueError("json invalido"))
    chamadas = []

    async def handler_original(req, background_tasks):
        chamadas.append(req)
        try:
            await req.json()
        except Exception as exc:
            return {"status": "erro_critico", "detalhe": str(exc)}

    monkeypatch.setattr(pix_recovery, "webhook_kiwify", handler_original)
    resposta = asyncio.run(
        pix_recovery.webhook_kiwify_com_pix(request, BackgroundTasks())
    )

    assert resposta == {"status": "erro_critico", "detalhe": "json invalido"}
    assert chamadas == [request]
    assert request.json_calls == 2


@pytest.mark.parametrize(
    ("payload", "tarefa_esperada"),
    [
        (payload_pix_plano(), pix_recovery.processar_pix_criado),
        (
            payload_pix_plano(
                order_status="paid", webhook_event_type="order_approved"
            ),
            pix_recovery.processar_job_pix,
        ),
    ],
)
def test_wrapper_chama_handler_original_uma_vez_e_agenda_pix(
    monkeypatch, payload, tarefa_esperada
):
    request = FakeRequest(payload=payload)
    request.query_params = {"signature": "valor-ignorado", "extra": "1"}
    chamadas = []
    tarefas = BackgroundTasks()

    async def handler_original(req, background_tasks):
        chamadas.append((req, background_tasks))
        return {"status": "processado"}

    monkeypatch.setattr(pix_recovery, "webhook_kiwify", handler_original)
    resposta = asyncio.run(pix_recovery.webhook_kiwify_com_pix(request, tarefas))

    assert resposta == {"status": "processado"}
    assert chamadas == [(request, tarefas)]
    assert len(tarefas.tasks) == 1
    assert tarefas.tasks[0].func is pix_recovery.processar_job_pix


def test_wrapper_cart_abandoned_preserva_handler_sem_efeito_pix(monkeypatch):
    payload = {
        "cart": {
            "status": "cart_abandoned",
            "email": "cart@example.com",
        }
    }
    request = FakeRequest(payload=payload)
    chamadas = []
    tarefas = BackgroundTasks()

    async def handler_original(req, background_tasks):
        chamadas.append(req)
        return {"status": "processado", "status_pagamento": "cart_abandoned"}

    monkeypatch.setattr(pix_recovery, "webhook_kiwify", handler_original)
    resposta = asyncio.run(pix_recovery.webhook_kiwify_com_pix(request, tarefas))

    assert resposta["status_pagamento"] == "cart_abandoned"
    assert chamadas == [request]
    assert tarefas.tasks == []


def test_payload_plano_sem_customer_usa_email_confirmado_pela_api(monkeypatch):
    payload = payload_pix_plano()
    payload.pop("Customer")
    chamadas = []
    monkeypatch.setattr(
        pix_recovery, "adquirir_processamento", lambda *args: chamadas.append(args)
    )

    pix_recovery.processar_pix_criado(payload)

    assert pix_recovery._dados_pix(payload)["email"] == ""
    assert len(chamadas) == 1
    assert chamadas[0][1] == "teste@example.com"


def test_payload_plano_sem_order_id_nao_classifica_nem_inicia_worker(monkeypatch):
    payload = payload_pix_plano()
    payload.pop("order_id")
    chamadas = []
    monkeypatch.setattr(
        pix_recovery, "adquirir_processamento", lambda *args: chamadas.append(args)
    )

    pix_recovery.processar_pix_criado(payload)

    assert pix_recovery._evento_pix_criado(payload) is False
    assert chamadas == []


def test_subscribe_usa_somente_api_secret(monkeypatch):
    enviados = []
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key-value")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret-value")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda url, **kwargs: enviados.append(kwargs["json"]) or FakeResponse(200),
    )

    assert pix_recovery._alterar_tag_kit("teste@example.com", "subscribe") is True
    assert enviados == [
        {"api_secret": "secret-value", "email": "teste@example.com"}
    ]
    assert "api_key" not in enviados[0]


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("Maria de Souza", "Maria"),
        ("  Maria  \t de\nSouza  ", "Maria"),
        (None, ""),
        ("   ", ""),
        ({"name": "Maria"}, ""),
    ],
)
def test_normaliza_primeiro_nome_de_forma_conservadora(nome, esperado):
    assert pix_recovery._primeiro_nome(nome) == esperado


def test_subscribe_com_nome_atualiza_subscriber_via_put(monkeypatch):
    posts = []
    puts = []
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key-value")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret-value")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda url, **kwargs: posts.append(kwargs["json"])
        or FakeResponse(200, {"subscription": {"subscriber": {"id": 123}}}),
    )
    monkeypatch.setattr(
        pix_recovery.requests,
        "put",
        lambda url, **kwargs: puts.append((url, kwargs)) or FakeResponse(200),
    )

    assert pix_recovery._alterar_tag_kit(
        "teste@example.com", "subscribe", "Maria"
    ) is True
    assert posts == [{"api_secret": "secret-value", "email": "teste@example.com"}]
    assert puts == [
        (
            "https://api.convertkit.com/v3/subscribers/123",
            {
                "json": {"api_secret": "secret-value", "first_name": "Maria"},
                "timeout": 5,
            },
        )
    ]


def test_subscribe_sem_nome_nao_inclui_first_name(monkeypatch):
    enviados = []
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret-value")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda url, **kwargs: enviados.append(kwargs["json"]) or FakeResponse(200),
    )

    assert pix_recovery._alterar_tag_kit(
        "teste@example.com", "subscribe", ""
    ) is True
    assert "first_name" not in enviados[0]
    assert "api_key" not in enviados[0]


@pytest.mark.parametrize(
    "put_result",
    [FakeResponse(400), FakeResponse(500), TimeoutError("timeout"), RuntimeError("erro")],
)
def test_falha_do_put_nao_altera_sucesso_da_tag_pix(monkeypatch, put_result):
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret-value")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda *a, **k: FakeResponse(
            200, {"subscription": {"subscriber": {"id": 123}}}
        ),
    )

    def put(*args, **kwargs):
        if isinstance(put_result, Exception):
            raise put_result
        return put_result

    monkeypatch.setattr(pix_recovery.requests, "put", put)

    assert pix_recovery._alterar_tag_kit(
        "teste@example.com", "subscribe", "Maria"
    ) is True


@pytest.mark.parametrize("json_data", [{}, ValueError("json invalido")])
def test_subscribe_sem_id_ou_json_valido_preserva_sucesso(monkeypatch, json_data):
    puts = []
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret-value")
    monkeypatch.setattr(
        pix_recovery.requests, "post", lambda *a, **k: FakeResponse(200, json_data)
    )
    monkeypatch.setattr(
        pix_recovery.requests, "put", lambda *a, **k: puts.append((a, k))
    )

    assert pix_recovery._alterar_tag_kit(
        "teste@example.com", "subscribe", "Maria"
    ) is True
    assert puts == []


def test_subscribe_sem_secret_nao_faz_fallback_para_api_key(monkeypatch):
    chamadas = []
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key-value")
    monkeypatch.delenv("CONVERTKIT_API_SECRET", raising=False)
    monkeypatch.setattr(
        pix_recovery.requests, "post", lambda *args, **kwargs: chamadas.append(kwargs)
    )

    assert pix_recovery._alterar_tag_kit("teste@example.com", "subscribe") is False
    assert chamadas == []


def test_subscribe_loga_somente_metadados_sanitizados(monkeypatch, capsys):
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret-value")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(
            201,
            {
                "subscription": {
                    "subscriber": {"id": 123, "first_name": "Maria"}
                }
            },
        ),
    )

    assert pix_recovery._alterar_tag_kit(
        "teste@example.com", "subscribe", "Maria"
    ) is True
    logs = capsys.readouterr().out
    assert "operation=subscribe" in logs
    assert "status_http=201" in logs
    assert "json_valid=True" in logs
    assert "subscriber_id_present=True" in logs
    assert "first_name_present=True" in logs
    assert "teste@example.com" not in logs
    assert "Maria" not in logs
    assert "123" not in logs


def test_unsubscribe_usa_somente_api_secret(monkeypatch):
    enviados = []
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key-value")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret-value")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda url, **kwargs: enviados.append(kwargs["json"]) or FakeResponse(204),
    )

    assert pix_recovery._alterar_tag_kit("teste@example.com", "unsubscribe") is True
    assert enviados == [
        {"api_secret": "secret-value", "email": "teste@example.com"}
    ]


def test_unsubscribe_nunca_inclui_first_name(monkeypatch):
    enviados = []
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret-value")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda url, **kwargs: enviados.append(kwargs["json"]) or FakeResponse(204),
    )

    assert pix_recovery._alterar_tag_kit(
        "teste@example.com", "unsubscribe", "Maria"
    ) is True
    assert "first_name" not in enviados[0]


def test_unsubscribe_sem_secret_nao_chama_kit(monkeypatch):
    chamadas = []
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_KEY", "key-value")
    monkeypatch.delenv("CONVERTKIT_API_SECRET", raising=False)
    monkeypatch.setattr(
        pix_recovery.requests, "post", lambda *args, **kwargs: chamadas.append(kwargs)
    )

    assert pix_recovery._alterar_tag_kit("teste@example.com", "unsubscribe") is False
    assert chamadas == []


@pytest.mark.parametrize("status_code", [401, 403, 500])
def test_unsubscribe_http_erro_mantem_falha(monkeypatch, status_code):
    monkeypatch.setenv("TAG_PIX_ID", "tag-pix")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret-value")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(status_code),
    )

    assert pix_recovery._alterar_tag_kit("teste@example.com", "unsubscribe") is False


def test_unsubscribe_timeout_mantem_cancelamento_pending(monkeypatch):
    monkeypatch.setattr(
        pix_recovery,
        "buscar_ledger",
        lambda order_id: {
            "email": "ledger@example.com",
            "status": "cancelled_pending_unsubscribe",
            "subscribe_attempted": True,
        },
    )
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda *args: (_ for _ in ()).throw(TimeoutError("timeout")),
    )

    assert pix_recovery.reconciliar_cancelamento("order-timeout") is False


def test_paid_repetido_repete_reconciliacao_sem_reabrir_recovery(monkeypatch):
    eventos = []
    monkeypatch.setattr(
        pix_recovery,
        "persistir_cancelamento",
        lambda *args: eventos.append("pending") or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento",
        lambda *args: eventos.append("unsubscribe") or True,
    )
    pago = payload_pix_plano(
        order_status="paid", webhook_event_type="order_approved"
    )

    pix_recovery.cancelar_pix_por_pagamento(pago)
    pix_recovery.cancelar_pix_por_pagamento(pago)

    assert eventos == ["pending", "unsubscribe", "pending", "unsubscribe"]


def test_pix_created_repetido_nao_reaplica_subscribe(monkeypatch):
    chamadas_kit = []
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: False)
    monkeypatch.setattr(pix_recovery, "reconciliar_cancelamento", lambda *args: False)
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda *args: chamadas_kit.append(args) or True,
    )

    pix_recovery.processar_pix_criado(payload_pix_plano())
    pix_recovery.processar_pix_criado(payload_pix_plano())

    assert chamadas_kit == []


def test_paid_depois_de_completed_persiste_pending_e_reconcilia(monkeypatch):
    eventos = []
    monkeypatch.setattr(
        pix_recovery,
        "persistir_cancelamento",
        lambda *args: eventos.append("completed->pending") or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento",
        lambda *args: eventos.append("unsubscribe") or True,
    )

    pix_recovery.cancelar_pix_por_pagamento(
        payload_pix_plano(order_status="paid", webhook_event_type="order_approved")
    )

    assert eventos == ["completed->pending", "unsubscribe"]


def test_migration_006_remove_constraint_antes_do_backfill_e_recria_depois():
    sql = (
        Path(__file__).parents[1] / "sql" / "006_upgrade_recovery_pix_orders.sql"
    ).read_text(encoding="utf-8").lower()
    drop_constraint = sql.index("drop constraint if exists recovery_pix_orders_status_check")
    backfill_cancelled = sql.index("set status = 'cancelled_pending_unsubscribe'")
    add_constraint = sql.index("add constraint recovery_pix_orders_status_check")

    assert drop_constraint < backfill_cancelled < add_constraint


def test_migration_006_guarda_tabela_ausente_e_backfill_unico():
    sql = (
        Path(__file__).parents[1] / "sql" / "006_upgrade_recovery_pix_orders.sql"
    ).read_text(encoding="utf-8").lower()

    assert "to_regclass('public.recovery_pix_orders') is not null" in sql
    assert "if not tabela_existe then\n        return;" in sql
    assert "if not subscribe_attempted_ja_existia then" in sql
    assert sql.count("set subscribe_attempted = true") == 1


def test_bootstrap_sem_monkeypatch_e_codigo_sem_debug_pix():
    raiz = Path(__file__).parents[1]
    bootstrap = (raiz / "tracking_boot.py").read_text(encoding="utf-8")
    codigo_pix = (raiz / "pix_recovery.py").read_text(encoding="utf-8")
    codigo_combinado = f"{bootstrap}\n{codigo_pix}"

    assert "pix_recovery._rpc_bool" not in bootstrap
    assert "pix_recovery._alterar_tag_kit" not in bootstrap
    for marcador in (
        "PIX DEBUG",
        "PIX SHAPE DEBUG",
        "PIX RPC DEBUG",
        "PIX KIT DEBUG",
        "PIX FLOW",
        "KIWIFY VERIFY",
    ):
        assert marcador not in codigo_combinado
    assert "_kiwify_verify_log" not in codigo_pix
    assert "_valor_kiwify_seguro_para_log" not in codigo_pix


def test_pix_recovery_prints_nao_referenciam_dados_sensiveis():
    caminho = Path(__file__).parents[1] / "pix_recovery.py"
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    prints = [
        ast.unparse(no).lower()
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Name)
        and no.func.id == "print"
    ]

    for chamada in prints:
        for sensivel in (
            "email",
            "telefone",
            "cpf",
            "pix_code",
            "order_id",
            "api_key",
            "api_secret",
            "client_id",
            "client_secret",
            "access_token",
            "account_id",
            "worker_token",
            "payload_recebido",
        ):
            assert sensivel not in chamada


def venda_api(
    order_id="46bc33eb-6e53-4b4d-a8f7-72757a84b4ef",
    status="waiting_payment",
    payment_method="pix",
    customer_name="Maria de Souza",
):
    return {
        "id": order_id,
        "status": status,
        "payment_method": payment_method,
        "customer": {"email": "oficial@example.com", "name": customer_name},
    }


def instalar_consulta_kiwify(monkeypatch, resposta):
    monkeypatch.setenv("KIWIFY_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(pix_recovery, "_obter_oauth_token_kiwify", lambda: "oauth-token")
    monkeypatch.setattr(pix_recovery.requests, "get", lambda *args, **kwargs: resposta)


def confirmar_real(
    order_id,
    statuses_aceitos,
    payment_method_esperado=None,
):
    return CONFIRMAR_VENDA_KIWIFY_REAL(
        order_id, statuses_aceitos, payment_method_esperado
    )


def test_venda_kiwify_valida_libera_pix_created(monkeypatch):
    instalar_consulta_kiwify(monkeypatch, FakeResponse(200, venda_api()))
    monkeypatch.setattr(pix_recovery, "confirmar_venda_kiwify", confirmar_real)
    eventos = []
    monkeypatch.setattr(
        pix_recovery,
        "adquirir_processamento",
        lambda order_id, email, token: eventos.append((order_id, email)) or True,
    )
    monkeypatch.setattr(pix_recovery, "transicionar", lambda *args: True)
    monkeypatch.setattr(pix_recovery, "_alterar_tag_kit", lambda *args: True)

    pix_recovery.processar_pix_criado(payload_pix_plano())

    assert eventos == [
        ("46bc33eb-6e53-4b4d-a8f7-72757a84b4ef", "oficial@example.com")
    ]


def test_venda_confirmada_propaga_primeiro_nome_ao_subscribe(monkeypatch):
    instalar_consulta_kiwify(monkeypatch, FakeResponse(200, venda_api()))
    monkeypatch.setattr(pix_recovery, "confirmar_venda_kiwify", confirmar_real)
    enviados = []
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: True)
    monkeypatch.setattr(pix_recovery, "transicionar", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda *args: enviados.append(args) or True,
    )

    assert pix_recovery.processar_pix_criado(payload_pix_plano()) is True
    assert enviados == [("oficial@example.com", "subscribe", "Maria")]


def test_venda_confirmada_sem_nome_preserva_subscribe_atual(monkeypatch):
    instalar_consulta_kiwify(
        monkeypatch, FakeResponse(200, venda_api(customer_name=None))
    )
    monkeypatch.setattr(pix_recovery, "confirmar_venda_kiwify", confirmar_real)
    enviados = []
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: True)
    monkeypatch.setattr(pix_recovery, "transicionar", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda *args: enviados.append(args) or True,
    )

    assert pix_recovery.processar_pix_criado(payload_pix_plano()) is True
    assert enviados == [("oficial@example.com", "subscribe")]


def test_venda_kiwify_valida_libera_paid(monkeypatch):
    instalar_consulta_kiwify(
        monkeypatch, FakeResponse(200, venda_api(status="paid"))
    )
    monkeypatch.setattr(pix_recovery, "confirmar_venda_kiwify", confirmar_real)
    eventos = []
    monkeypatch.setattr(
        pix_recovery,
        "persistir_cancelamento",
        lambda order_id, email: eventos.append(("cancel", order_id, email)) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento",
        lambda order_id, email: eventos.append(("unsubscribe", order_id, email)) or True,
    )

    pix_recovery.cancelar_pix_por_pagamento(
        payload_pix_plano(order_status="paid", webhook_event_type="order_approved")
    )

    assert eventos == [
        (
            "cancel",
            "46bc33eb-6e53-4b4d-a8f7-72757a84b4ef",
            "oficial@example.com",
        ),
        (
            "unsubscribe",
            "46bc33eb-6e53-4b4d-a8f7-72757a84b4ef",
            "oficial@example.com",
        ),
    ]


@pytest.mark.parametrize("status_code", [401, 403, 404, 429, 500])
def test_consulta_kiwify_http_erro_falha_fechada(monkeypatch, status_code):
    instalar_consulta_kiwify(monkeypatch, FakeResponse(status_code, {}))

    assert confirmar_real(
        "order-1", pix_recovery.KIWIFY_PENDING_STATUSES, "pix"
    ) == {}


def test_consulta_kiwify_timeout_falha_fechada(monkeypatch):
    monkeypatch.setenv("KIWIFY_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(pix_recovery, "_obter_oauth_token_kiwify", lambda: "oauth-token")
    monkeypatch.setattr(
        pix_recovery.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timeout")),
    )

    assert confirmar_real("order-1", {"paid"}) == {}


def test_consulta_kiwify_json_invalido_falha_fechada(monkeypatch):
    instalar_consulta_kiwify(
        monkeypatch, FakeResponse(200, json_error=ValueError("json invalido"))
    )

    assert confirmar_real("order-1", {"paid"}) == {}


def test_consulta_kiwify_order_id_diferente_falha_fechada(monkeypatch):
    instalar_consulta_kiwify(
        monkeypatch, FakeResponse(200, venda_api(order_id="outra-order"))
    )

    assert confirmar_real(
        "order-1", pix_recovery.KIWIFY_PENDING_STATUSES, "pix"
    ) == {}


def test_consulta_kiwify_status_diferente_rejeita_forged_paid(monkeypatch):
    instalar_consulta_kiwify(
        monkeypatch, FakeResponse(200, venda_api(order_id="order-1", status="pending"))
    )

    assert confirmar_real("order-1", {"paid"}) == {}


def test_consulta_kiwify_status_diferente_rejeita_forged_pix(monkeypatch):
    instalar_consulta_kiwify(
        monkeypatch, FakeResponse(200, venda_api(order_id="order-1", status="paid"))
    )

    assert confirmar_real(
        "order-1", pix_recovery.KIWIFY_PENDING_STATUSES, "pix"
    ) == {}


def test_consulta_kiwify_payment_method_diferente_falha_fechada(monkeypatch):
    instalar_consulta_kiwify(
        monkeypatch,
        FakeResponse(
            200,
            venda_api(order_id="order-1", status="pending", payment_method="boleto"),
        ),
    )

    assert confirmar_real(
        "order-1", pix_recovery.KIWIFY_PENDING_STATUSES, "pix"
    ) == {}


@pytest.mark.parametrize("evento", ["pix", "paid"])
def test_falha_verificacao_nao_chama_kit_supabase_ou_transicao(monkeypatch, evento):
    efeitos = []
    monkeypatch.setattr(pix_recovery, "confirmar_venda_kiwify", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        pix_recovery, "adquirir_processamento", lambda *args: efeitos.append("acquire")
    )
    monkeypatch.setattr(
        pix_recovery, "persistir_cancelamento", lambda *args: efeitos.append("cancel")
    )
    monkeypatch.setattr(
        pix_recovery, "transicionar", lambda *args: efeitos.append("transition")
    )
    monkeypatch.setattr(
        pix_recovery, "_alterar_tag_kit", lambda *args: efeitos.append("kit")
    )
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento",
        lambda *args: efeitos.append("unsubscribe"),
    )

    if evento == "pix":
        pix_recovery.processar_pix_criado(payload_pix_plano())
    else:
        pix_recovery.cancelar_pix_por_pagamento(
            payload_pix_plano(order_status="paid", webhook_event_type="order_approved")
        )

    assert efeitos == []


def test_oauth_kiwify_usa_credenciais_e_cache(monkeypatch):
    chamadas = []
    monkeypatch.setenv("KIWIFY_API_CLIENT_ID", "client-id")
    monkeypatch.setenv("KIWIFY_API_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(pix_recovery.time, "monotonic", lambda: 1000.0)
    pix_recovery._kiwify_oauth_cache.update(access_token="", expires_at=0.0)
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda url, **kwargs: chamadas.append((url, kwargs))
        or FakeResponse(200, {"access_token": "oauth-token", "expires_in": 3600}),
    )

    assert pix_recovery._obter_oauth_token_kiwify() == "oauth-token"
    assert pix_recovery._obter_oauth_token_kiwify() == "oauth-token"
    assert len(chamadas) == 1
    assert chamadas[0][1]["data"] == {
        "client_id": "client-id",
        "client_secret": "client-secret",
    }


def test_credenciais_kiwify_ausentes_falham_sem_chamada_externa(monkeypatch):
    chamadas = []
    monkeypatch.delenv("KIWIFY_API_CLIENT_ID", raising=False)
    monkeypatch.delenv("KIWIFY_API_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("KIWIFY_ACCOUNT_ID", raising=False)
    pix_recovery._kiwify_oauth_cache.update(access_token="", expires_at=0.0)
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda *args, **kwargs: chamadas.append("oauth"),
    )
    monkeypatch.setattr(
        pix_recovery.requests,
        "get",
        lambda *args, **kwargs: chamadas.append("sale"),
    )

    assert pix_recovery._obter_oauth_token_kiwify() == ""
    assert confirmar_real("order-1", {"paid"}) == {}
    assert chamadas == []


def test_webhook_persiste_job_antes_do_handler_e_sobrevive_sem_worker(monkeypatch):
    eventos = []
    request = FakeRequest(payload=payload_pix_plano())
    tarefas = BackgroundTasks()

    monkeypatch.setattr(
        pix_recovery,
        "enfileirar_job_pix",
        lambda order_id, event_type: eventos.append(("persisted", event_type)) or True,
    )

    async def handler_original(req, background_tasks):
        eventos.append(("handler", None))
        return {"status": "processado"}

    monkeypatch.setattr(pix_recovery, "webhook_kiwify", handler_original)

    resposta = asyncio.run(pix_recovery.webhook_kiwify_com_pix(request, tarefas))

    assert resposta == {"status": "processado"}
    assert eventos == [("persisted", "pix_created"), ("handler", None)]
    assert len(tarefas.tasks) == 1
    # Simula crash: a tarefa não é executada, mas o enqueue já foi confirmado.


def test_reprocessamento_posterior_conclui_job(monkeypatch):
    eventos = []
    monkeypatch.setattr(pix_recovery, "uuid4", lambda: "job-token")
    monkeypatch.setattr(
        pix_recovery,
        "adquirir_job_pix",
        lambda order_id, event_type, token: eventos.append(("acquire", token)) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "processar_pix_criado",
        lambda payload: eventos.append(("effect", payload["webhook_event_type"])) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "concluir_job_pix",
        lambda order_id, event_type, token: eventos.append(("complete", token)) or True,
    )

    assert pix_recovery.processar_job_pix("order-1", "pix_created") is True
    assert eventos == [
        ("acquire", "job-token"),
        ("effect", "pix_created"),
        ("complete", "job-token"),
    ]


def test_webhook_duplicado_nao_cria_dois_jobs_logicos(monkeypatch):
    jobs = set()
    request = FakeRequest(payload=payload_pix_plano())

    def enqueue(order_id, event_type):
        jobs.add((order_id, event_type))
        return True

    async def handler_original(req, background_tasks):
        return {"status": "processado"}

    monkeypatch.setattr(pix_recovery, "enfileirar_job_pix", enqueue)
    monkeypatch.setattr(pix_recovery, "webhook_kiwify", handler_original)

    asyncio.run(pix_recovery.webhook_kiwify_com_pix(request, BackgroundTasks()))
    asyncio.run(pix_recovery.webhook_kiwify_com_pix(request, BackgroundTasks()))

    assert jobs == {
        ("46bc33eb-6e53-4b4d-a8f7-72757a84b4ef", "pix_created")
    }


def test_dois_workers_tem_um_unico_vencedor(monkeypatch):
    aquisicoes = iter([True, False])
    efeitos = []
    monkeypatch.setattr(
        pix_recovery, "adquirir_job_pix", lambda *args: next(aquisicoes)
    )
    monkeypatch.setattr(
        pix_recovery,
        "processar_pix_criado",
        lambda payload: efeitos.append("effect") or True,
    )
    monkeypatch.setattr(pix_recovery, "concluir_job_pix", lambda *args: True)

    assert pix_recovery.processar_job_pix("order-1", "pix_created") is True
    assert pix_recovery.processar_job_pix("order-1", "pix_created") is False
    assert efeitos == ["effect"]


def test_job_stale_e_recuperavel_por_cas_na_migration_007():
    sql = (
        Path(__file__).parents[1] / "sql" / "007_create_recovery_pix_jobs.sql"
    ).read_text(encoding="utf-8").lower()

    assert "primary key (order_id, event_type)" in sql
    assert "status in ('pending', 'retryable')" in sql
    assert "status = 'processing'" in sql
    assert "updated_at < now() - make_interval" in sql
    assert "and attempt_token = p_attempt_token" in sql
    assert "attempts = attempts + 1" in sql
    assert "revoke all on table public.recovery_pix_jobs from public, anon, authenticated" in sql
    assert "grant select, insert, update on table public.recovery_pix_jobs to service_role" in sql


@pytest.mark.parametrize("falha", ["kiwify_5xx", "kiwify_timeout", "kit_timeout"])
def test_falha_externa_mantem_job_retryable(monkeypatch, falha):
    falhas = []
    monkeypatch.setattr(pix_recovery, "adquirir_job_pix", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "falhar_job_pix",
        lambda order_id, event_type, token, retryable=True: falhas.append(retryable)
        or True,
    )
    if falha in {"kiwify_5xx", "kiwify_timeout"}:
        monkeypatch.setattr(pix_recovery, "processar_pix_criado", lambda payload: False)
    else:
        monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: True)
        monkeypatch.setattr(pix_recovery, "transicionar", lambda *args: True)
        monkeypatch.setattr(
            pix_recovery,
            "_alterar_tag_kit",
            lambda *args: (_ for _ in ()).throw(TimeoutError("timeout")),
        )
        monkeypatch.setattr(
            pix_recovery, "compensar_subscribe_concorrente", lambda *args: False
        )

    assert pix_recovery.processar_job_pix("order-1", "pix_created") is False
    assert falhas == [True]


def test_falha_kit_com_primeiro_nome_mantem_job_retryable(monkeypatch):
    falhas = []
    monkeypatch.setattr(pix_recovery, "adquirir_job_pix", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_venda_kiwify",
        lambda *args, **kwargs: {
            "id": "order-1",
            "status": "waiting_payment",
            "payment_method": "pix",
            "email": "teste@example.com",
            "first_name": "Maria",
        },
    )
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: True)
    monkeypatch.setattr(pix_recovery, "transicionar", lambda *args: True)
    monkeypatch.setattr(pix_recovery, "compensar_subscribe_concorrente", lambda *args: False)
    monkeypatch.setattr(pix_recovery, "_alterar_tag_kit", lambda *args: False)
    monkeypatch.setattr(
        pix_recovery,
        "falhar_job_pix",
        lambda order_id, event_type, token, retryable=True: falhas.append(retryable)
        or True,
    )

    assert pix_recovery.processar_job_pix("order-1", "pix_created") is False
    assert falhas == [True]


def test_paid_e_pix_jobs_preservam_ordering_conservador(monkeypatch):
    eventos = []
    monkeypatch.setattr(pix_recovery, "adquirir_job_pix", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "cancelar_pix_por_pagamento",
        lambda payload: eventos.append("paid") or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "processar_pix_criado",
        lambda payload: eventos.append("pix_after_paid_noop") or True,
    )
    monkeypatch.setattr(pix_recovery, "concluir_job_pix", lambda *args: True)

    assert pix_recovery.processar_job_pix("order-1", "paid") is True
    assert pix_recovery.processar_job_pix("order-1", "pix_created") is True
    assert eventos == ["paid", "pix_after_paid_noop"]


def test_cart_abandoned_nao_enfileira_job_pix(monkeypatch):
    enfileirados = []
    request = FakeRequest(
        payload={"cart": {"status": "cart_abandoned", "email": "cart@example.com"}}
    )
    monkeypatch.setattr(
        pix_recovery,
        "enfileirar_job_pix",
        lambda *args: enfileirados.append(args) or True,
    )

    async def handler_original(req, background_tasks):
        return {"status": "processado"}

    monkeypatch.setattr(pix_recovery, "webhook_kiwify", handler_original)

    asyncio.run(pix_recovery.webhook_kiwify_com_pix(request, BackgroundTasks()))

    assert enfileirados == []


def test_enqueue_falha_impede_ack_200_mas_handler_roda_uma_vez(monkeypatch):
    chamadas = []
    request = FakeRequest(payload=payload_pix_plano())
    monkeypatch.setattr(pix_recovery, "enfileirar_job_pix", lambda *args: False)

    async def handler_original(req, background_tasks):
        chamadas.append(req)
        return {"status": "processado"}

    monkeypatch.setattr(pix_recovery, "webhook_kiwify", handler_original)

    with pytest.raises(Exception) as erro:
        asyncio.run(
            pix_recovery.webhook_kiwify_com_pix(request, BackgroundTasks())
        )

    assert getattr(erro.value, "status_code", None) == 503
    assert chamadas == [request]


def test_reconciliador_independente_reprocessa_jobs_persistidos(monkeypatch):
    processados = []
    monkeypatch.setattr(
        pix_recovery,
        "listar_jobs_pix_recuperaveis",
        lambda limit: [
            {"order_id": "order-1", "event_type": "pix_created"},
            {"order_id": "order-2", "event_type": "paid"},
        ],
    )
    monkeypatch.setattr(
        pix_recovery,
        "processar_job_pix",
        lambda order_id, event_type: processados.append((order_id, event_type)) or True,
    )

    resultado = pix_recovery.reconciliar_jobs_pix(limit=10)

    assert resultado == {"candidates": 2, "completed": 2, "attempted": 2}
    assert processados == [("order-1", "pix_created"), ("order-2", "paid")]


def test_endpoint_reconciliacao_exige_bearer_configurado(monkeypatch):
    request = FakeRequest()
    monkeypatch.setenv("PIX_RECOVERY_WORKER_TOKEN", "worker-secret")

    with pytest.raises(Exception) as erro:
        pix_recovery._autorizar_reconciliacao(request)
    assert getattr(erro.value, "status_code", None) == 401

    request.headers = {"Authorization": "Bearer worker-secret"}
    pix_recovery._autorizar_reconciliacao(request)


def test_endpoint_reconciliacao_usa_compare_digest():
    codigo = (
        Path(__file__).parents[1] / "pix_recovery.py"
    ).read_text(encoding="utf-8")

    assert "hmac.compare_digest(recebido, segredo)" in codigo


def test_migration_008_converge_permissoes_minimas():
    sql = (
        Path(__file__).parents[1] / "sql" / "008_harden_recovery_pix_permissions.sql"
    ).read_text(encoding="utf-8").lower()

    assert "recovery_pix_orders enable row level security" in sql
    assert "recovery_pix_jobs enable row level security" in sql
    assert "revoke all on table public.recovery_pix_orders from public, anon, authenticated" in sql
    assert "revoke all on table public.recovery_pix_jobs from public, anon, authenticated" in sql
    assert "revoke all on table public.recovery_pix_orders from service_role" in sql
    assert "revoke all on table public.recovery_pix_jobs from service_role" in sql
    assert "grant select on table public.recovery_pix_orders to service_role" in sql
    assert "grant select on table public.recovery_pix_jobs to service_role" in sql
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert sql.count("from public, anon, authenticated") == 11
    assert sql.count("to service_role") == 11


def test_migrations_005_006_007_008_formam_caminho_limpo_e_upgrade():
    raiz = Path(__file__).parents[1] / "sql"
    m005 = (raiz / "005_create_recovery_pix_orders.sql").read_text(encoding="utf-8").lower()
    m006 = (raiz / "006_upgrade_recovery_pix_orders.sql").read_text(encoding="utf-8").lower()
    m007 = (raiz / "007_create_recovery_pix_jobs.sql").read_text(encoding="utf-8").lower()
    m008 = (raiz / "008_harden_recovery_pix_permissions.sql").read_text(encoding="utf-8").lower()

    assert "create table if not exists public.recovery_pix_orders" in m005
    assert "to_regclass('public.recovery_pix_orders') is not null" in m006
    assert "create table if not exists public.recovery_pix_jobs" in m007
    assert "primary key (order_id, event_type)" in m007
    assert "recovery_pix_orders enable row level security" in m008
    assert "recovery_pix_jobs enable row level security" in m008


def test_logs_operacionais_nao_imprimem_exception_message(monkeypatch, capsys):
    segredo = "email-token-order-id-ultrassecreto"
    monkeypatch.setattr(
        pix_recovery.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(segredo)),
    )

    assert pix_recovery.listar_jobs_pix_recuperaveis() == []
    logs = capsys.readouterr().out

    assert "[PIX Job] Falha ao consultar jobs: RuntimeError" in logs
    assert segredo not in logs
