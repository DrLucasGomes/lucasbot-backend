import asyncio
import ast
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

import pix_recovery


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
    def __init__(self, status_code):
        self.status_code = status_code


class FakeRequest:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.json_calls = 0

    async def json(self):
        self.json_calls += 1
        if self.error:
            raise self.error
        return self.payload


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

    assert eventos == [("46bc33eb-6e53-4b4d-a8f7-72757a84b4ef", "")]


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


def test_payload_plano_sem_customer_nao_inicia_worker(monkeypatch):
    payload = payload_pix_plano()
    payload.pop("Customer")
    chamadas = []
    monkeypatch.setattr(
        pix_recovery, "adquirir_processamento", lambda *args: chamadas.append(args)
    )

    pix_recovery.processar_pix_criado(payload)

    assert pix_recovery._dados_pix(payload)["email"] == ""
    assert chamadas == []


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


def test_subscribe_usa_somente_api_key(monkeypatch):
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
    assert enviados == [{"api_key": "key-value", "email": "teste@example.com"}]


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
    ):
        assert marcador not in codigo_combinado


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
        ):
            assert sensivel not in chamada
