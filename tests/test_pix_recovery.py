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
