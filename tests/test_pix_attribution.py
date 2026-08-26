from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pix_attribution
import pix_recovery


class FakeResponse:
    def __init__(self, status_code=201):
        self.status_code = status_code


def _pix_payload(order_id="order-1"):
    return {
        "order": {
            "order_id": order_id,
            "webhook_event_type": "pix_created",
            "payment_method": "pix",
            "order_status": "waiting_payment",
            "Customer": {"email": "lead@example.com"},
        }
    }


def _paid_payload(order_id="order-1"):
    return {
        "order": {
            "order_id": order_id,
            "webhook_event_type": "order_approved",
            "order_status": "paid",
            "Customer": {"email": "lead@example.com"},
        }
    }


def _install_successful_recovery(monkeypatch):
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_venda_kiwify",
        lambda *a, **k: {
            "id": "order-1",
            "status": "waiting_payment",
            "payment_method": "pix",
            "email": "lead@example.com",
            "first_name": "",
        },
    )
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *a: True)
    monkeypatch.setattr(pix_recovery, "transicionar", lambda *a: True)
    monkeypatch.setattr(pix_recovery, "_alterar_tag_kit", lambda *a: True)


def test_recovery_entered_somente_apos_tag_e_transicao_confirmadas(monkeypatch):
    _install_successful_recovery(monkeypatch)
    events = []
    monkeypatch.setattr(
        pix_recovery,
        "registrar_evento_atribuicao_pix",
        lambda *args: events.append(args) or True,
    )

    assert pix_recovery.processar_pix_criado(_pix_payload()) is True
    assert events == [("order-1", "recovery_entered")]


def test_falha_da_tag_nao_registra_recovery_entered(monkeypatch):
    _install_successful_recovery(monkeypatch)
    events = []
    monkeypatch.setattr(pix_recovery, "_alterar_tag_kit", lambda *a: False)
    monkeypatch.setattr(
        pix_recovery, "compensar_subscribe_concorrente", lambda *a: False
    )
    monkeypatch.setattr(
        pix_recovery,
        "registrar_evento_atribuicao_pix",
        lambda *args: events.append(args) or True,
    )

    assert pix_recovery.processar_pix_criado(_pix_payload()) is False
    assert events == []


def test_falha_da_transicao_final_nao_registra_recovery_entered(monkeypatch):
    _install_successful_recovery(monkeypatch)
    events = []
    transitions = iter([True, False])
    monkeypatch.setattr(
        pix_recovery, "transicionar", lambda *a: next(transitions)
    )
    monkeypatch.setattr(
        pix_recovery, "compensar_subscribe_concorrente", lambda *a: False
    )
    monkeypatch.setattr(
        pix_recovery,
        "registrar_evento_atribuicao_pix",
        lambda *args: events.append(args) or True,
    )

    assert pix_recovery.processar_pix_criado(_pix_payload()) is False
    assert events == []


def test_retry_com_ledger_completed_recupera_evento_idempotente(monkeypatch):
    _install_successful_recovery(monkeypatch)
    events = []
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *a: False)
    monkeypatch.setattr(
        pix_recovery, "buscar_ledger", lambda *a: {"status": "completed"}
    )
    monkeypatch.setattr(
        pix_recovery,
        "registrar_evento_atribuicao_pix",
        lambda *args: events.append(args) or True,
    )

    assert pix_recovery.processar_pix_criado(_pix_payload()) is True
    assert events == [("order-1", "recovery_entered")]


def test_purchase_completed_depois_de_paid_validado(monkeypatch):
    events = []
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_venda_kiwify",
        lambda *a, **k: {"id": "order-1", "status": "paid", "email": "lead@example.com"},
    )
    monkeypatch.setattr(pix_recovery, "persistir_cancelamento", lambda *a: True)
    monkeypatch.setattr(pix_recovery, "reconciliar_cancelamento", lambda *a: True)
    monkeypatch.setattr(
        pix_recovery,
        "registrar_evento_atribuicao_pix",
        lambda *args: events.append(args) or True,
    )

    assert pix_recovery.cancelar_pix_por_pagamento(_paid_payload()) is True
    assert events == [("order-1", "purchase_completed")]


def test_paid_invalido_nao_registra_purchase_completed(monkeypatch):
    events = []
    monkeypatch.setattr(pix_recovery, "confirmar_venda_kiwify", lambda *a, **k: {})
    monkeypatch.setattr(
        pix_recovery,
        "registrar_evento_atribuicao_pix",
        lambda *args: events.append(args) or True,
    )

    assert pix_recovery.cancelar_pix_por_pagamento(_paid_payload()) is False
    assert events == []


def test_paid_validado_registra_mesmo_se_efeito_operacional_precisar_retry(monkeypatch):
    events = []
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_venda_kiwify",
        lambda *a, **k: {"id": "order-1", "status": "paid", "email": "lead@example.com"},
    )
    monkeypatch.setattr(pix_recovery, "persistir_cancelamento", lambda *a: False)
    monkeypatch.setattr(
        pix_recovery,
        "registrar_evento_atribuicao_pix",
        lambda *args: events.append(args) or True,
    )

    assert pix_recovery.cancelar_pix_por_pagamento(_paid_payload()) is False
    assert events == [("order-1", "purchase_completed")]


def test_mesmo_order_id_correlaciona_entrada_e_compra(monkeypatch):
    events = []
    _install_successful_recovery(monkeypatch)
    monkeypatch.setattr(
        pix_recovery,
        "registrar_evento_atribuicao_pix",
        lambda *args: events.append(args) or True,
    )
    assert pix_recovery.processar_pix_criado(_pix_payload()) is True

    monkeypatch.setattr(
        pix_recovery,
        "confirmar_venda_kiwify",
        lambda *a, **k: {"id": "order-1", "status": "paid", "email": "lead@example.com"},
    )
    monkeypatch.setattr(pix_recovery, "persistir_cancelamento", lambda *a: True)
    monkeypatch.setattr(pix_recovery, "reconciliar_cancelamento", lambda *a: True)
    assert pix_recovery.cancelar_pix_por_pagamento(_paid_payload()) is True

    assert events == [
        ("order-1", "recovery_entered"),
        ("order-1", "purchase_completed"),
    ]


def test_insert_analitico_fail_open_e_sem_pii(monkeypatch):
    _install_successful_recovery(monkeypatch)
    monkeypatch.setenv("SUPABASE_KEY", "supabase-secret")
    attempts = []

    def fail(*args, **kwargs):
        attempts.append(kwargs)
        raise TimeoutError("lead@example.com")

    monkeypatch.setattr(pix_attribution._ATTRIBUTION_SESSION, "post", fail)

    assert pix_recovery.processar_pix_criado(_pix_payload()) is True
    assert len(attempts) == 1
    assert attempts[0]["json"] == {
        "order_id": "order-1",
        "event_name": "recovery_entered",
        "dedupe_key": "recovery_entered:order-1",
    }
    serialized = repr(attempts[0]["json"])
    assert "lead@example.com" not in serialized
    assert "supabase-secret" not in serialized


def test_excecao_inesperada_do_helper_analitico_eh_fail_open(monkeypatch):
    _install_successful_recovery(monkeypatch)
    monkeypatch.setattr(
        pix_recovery,
        "registrar_evento_atribuicao_pix",
        lambda *a: (_ for _ in ()).throw(RuntimeError("PII lead@example.com")),
    )

    assert pix_recovery.processar_pix_criado(_pix_payload()) is True


def test_retries_e_concorrencia_usam_mesma_dedupe_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_KEY", "supabase-secret")
    payloads = []

    def post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return FakeResponse(201)

    monkeypatch.setattr(pix_attribution._ATTRIBUTION_SESSION, "post", post)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _: pix_attribution.registrar_evento_atribuicao_pix(
                    "order-1", "recovery_entered"
                ),
                range(8),
            )
        )

    assert all(results)
    assert {payload["dedupe_key"] for payload in payloads} == {
        "recovery_entered:order-1"
    }
    assert all(payload["order_id"] == "order-1" for payload in payloads)


def test_migration_append_only_idempotente_sem_pii_e_view_temporal():
    sql = (
        Path(__file__).resolve().parents[1]
        / "sql"
        / "009_create_recovery_pix_attribution_events.sql"
    ).read_text(encoding="utf-8").lower()

    assert "dedupe_key text not null unique" in sql
    assert "before update or delete" in sql
    assert "enable row level security" in sql
    assert "recovery_pix_entered_at is not null" in sql
    assert "purchase_completed_at is not null" in sql
    assert "purchase_completed_at >= recovery_pix_entered_at" in sql
    assert "extract(epoch from (purchase_completed_at - recovery_pix_entered_at))" in sql
    for pii in ("email", "telefone", "phone", "first_name", "nome"):
        assert pii not in sql
