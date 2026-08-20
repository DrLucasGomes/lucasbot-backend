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
    dados = payload_pix(webhook_event_type="order_created")
    assert pix_recovery._evento_pix_criado(dados) is False


def test_metodo_nao_pix_nao_dispara_pix():
    dados = payload_pix(payment_method="boleto")
    assert pix_recovery._evento_pix_criado(dados) is False


def test_pagamento_aprovado_e_evento_terminal():
    dados = payload_pix(order_status="paid", webhook_event_type="order_approved")
    assert pix_recovery._evento_pago(dados) is True


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


def test_pagamento_remove_tag_pix_e_cancela_ledger(monkeypatch):
    tags = []
    estados = []
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_kit",
        lambda email, acao: tags.append((email, acao)) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "atualizar_status",
        lambda order_id, status: estados.append((order_id, status)) or True,
    )

    dados = payload_pix(order_status="paid", webhook_event_type="order_approved")
    pix_recovery.cancelar_pix_por_pagamento(dados)

    assert tags == [("teste@example.com", "unsubscribe")]
    assert estados == [
        ("46bc33eb-6e53-4b4d-a8f7-72757a84b4ef", "cancelled")
    ]
