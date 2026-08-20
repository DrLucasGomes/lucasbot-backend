import pix_recovery


def payload_pix(**overrides):
    order = {
        "order_id": "46bc33eb-6e53-4b4d-a8f7-72757a84b4ef",
        "order_ref": "wIwmL6D",
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
    assert pix_recovery._evento_pix_criado(
        payload_pix(webhook_event_type="order_created")
    ) is False


def test_metodo_nao_pix_nao_dispara_pix():
    assert pix_recovery._evento_pix_criado(payload_pix(payment_method="boleto")) is False


def test_status_nao_waiting_payment_nao_dispara_pix():
    assert pix_recovery._evento_pix_criado(payload_pix(order_status="pending")) is False


def test_order_id_ausente_nao_dispara_pix():
    assert pix_recovery._evento_pix_criado(payload_pix(order_id="")) is False


def test_pagamento_aprovado_e_evento_terminal():
    dados = payload_pix(order_status="paid", webhook_event_type="order_approved")
    assert pix_recovery._evento_pago(dados) is True


def test_pix_valido_faz_transicoes_e_aplica_tag(monkeypatch):
    eventos = []
    monkeypatch.setattr(
        pix_recovery,
        "adquirir_processamento",
        lambda order_id, email: eventos.append(("acquire", order_id, email)) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "transicionar",
        lambda order_id, origem, destino: eventos.append(
            ("transition", origem, destino)
        )
        or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda email, acao: eventos.append(("kit", acao, email)) or True,
    )

    pix_recovery.processar_pix_criado(payload_pix())

    assert eventos[0][0] == "acquire"
    assert ("transition", "processing", "subscribing") in eventos
    assert ("kit", "subscribe", "teste@example.com") in eventos
    assert ("transition", "subscribing", "completed") in eventos


def test_order_id_duplicado_nao_reaplica_tag(monkeypatch):
    chamadas = []
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: False)
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda *args: chamadas.append(args) or True,
    )

    pix_recovery.processar_pix_criado(payload_pix())
    assert chamadas == []


def test_falha_do_kit_marca_failed_sem_completed(monkeypatch):
    transicoes = []
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery,
        "transicionar",
        lambda order_id, origem, destino: transicoes.append((origem, destino)) or True,
    )
    monkeypatch.setattr(pix_recovery, "_alterar_tag_kit", lambda *args: False)

    pix_recovery.processar_pix_criado(payload_pix())

    assert ("processing", "subscribing") in transicoes
    assert ("subscribing", "failed") in transicoes
    assert ("subscribing", "completed") not in transicoes


def test_paid_antes_pix_impede_subscribe(monkeypatch):
    tags = []
    tombstone = {"cancelled": False}

    def cancelar(order_id, email):
        tombstone["cancelled"] = True
        return True

    def adquirir(order_id, email):
        return not tombstone["cancelled"]

    monkeypatch.setattr(pix_recovery, "persistir_cancelamento", cancelar)
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", adquirir)
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda email, acao: tags.append(acao) or True,
    )

    pago = payload_pix(order_status="paid", webhook_event_type="order_approved")
    pix_recovery.cancelar_pix_por_pagamento(pago)
    pix_recovery.processar_pix_criado(payload_pix())

    assert tags == ["unsubscribe"]


def test_paid_concorrente_compensa_subscribe(monkeypatch):
    tags = []
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *args: True)

    def transicao(order_id, origem, destino):
        if (origem, destino) == ("processing", "subscribing"):
            return True
        if (origem, destino) == ("subscribing", "completed"):
            return False  # paid venceu a corrida e gravou cancelled
        return True

    monkeypatch.setattr(pix_recovery, "transicionar", transicao)
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda email, acao: tags.append(acao) or True,
    )

    pix_recovery.processar_pix_criado(payload_pix())

    assert tags == ["subscribe", "unsubscribe"]


def test_pagamento_persiste_cancelled_antes_de_unsubscribe(monkeypatch):
    eventos = []
    monkeypatch.setattr(
        pix_recovery,
        "persistir_cancelamento",
        lambda order_id, email: eventos.append("cancelled") or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda email, acao: eventos.append(acao) or True,
    )

    pago = payload_pix(order_status="paid", webhook_event_type="order_approved")
    pix_recovery.cancelar_pix_por_pagamento(pago)

    assert eventos == ["cancelled", "unsubscribe"]


def test_pagamento_sem_email_pode_usar_email_do_ledger(monkeypatch):
    tags = []
    monkeypatch.setattr(pix_recovery, "persistir_cancelamento", lambda *args: True)
    monkeypatch.setattr(
        pix_recovery, "buscar_email_ledger", lambda order_id: "ledger@example.com"
    )
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda email, acao: tags.append((email, acao)) or True,
    )

    pago = payload_pix(
        order_status="paid",
        webhook_event_type="order_approved",
        Customer={},
    )
    pix_recovery.cancelar_pix_por_pagamento(pago)

    assert tags == [("ledger@example.com", "unsubscribe")]
