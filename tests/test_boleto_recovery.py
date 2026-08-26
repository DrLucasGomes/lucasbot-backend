import asyncio
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

import pix_recovery


ORDER_ID = "bce89324-3dff-4bcb-89e4-10b035a9867b"
CONFIRMAR_VENDA_REAL = pix_recovery.confirmar_venda_kiwify


def payload_boleto(**overrides):
    order = {
        "order_id": ORDER_ID,
        "webhook_event_type": "billet_created",
        "payment_method": "boleto",
        "order_status": "waiting_payment",
        "boleto_URL": "https://example.invalid/boleto",
        "boleto_barcode": "nao-persistir-123",
        "boleto_expiry_date": "31/08/2026",
        "Customer": {
            "email": "boleto@example.com",
            "first_name": "Maria",
            "full_name": "Maria de Souza",
        },
    }
    order.update(overrides)
    return {"order": order}


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload
        self.query_params = {}
        self.headers = {}

    async def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def venda_boleto_confirmada(monkeypatch):
    monkeypatch.setattr(
        pix_recovery,
        "confirmar_venda_kiwify",
        lambda order_id, statuses_aceitos, payment_method_esperado=None: {
            "id": order_id,
            "status": "paid" if "paid" in statuses_aceitos else "waiting_payment",
            "payment_method": payment_method_esperado or "boleto",
            "email": "oficial@example.com",
            "first_name": "Maria",
        },
    )


def test_classifica_contrato_real_billet_created():
    assert pix_recovery._evento_boleto_criado(payload_boleto()) is True
    assert pix_recovery._evento_pix_criado(payload_boleto()) is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"order_id": ""},
        {"webhook_event_type": "boleto_created"},
        {"payment_method": "pix"},
        {"order_status": "pending"},
    ],
)
def test_rejeita_contrato_boleto_divergente(overrides):
    assert pix_recovery._evento_boleto_criado(payload_boleto(**overrides)) is False


def test_pix_nao_classificado_como_boleto():
    payload = payload_boleto(
        webhook_event_type="pix_created", payment_method="pix"
    )
    assert pix_recovery._evento_boleto_criado(payload) is False


def test_parse_vencimento_dd_mm_yyyy_sem_acao_temporal():
    assert pix_recovery._parse_boleto_expiry_date("31/08/2026") == (
        "2026-08-31T00:00:00+00:00"
    )


@pytest.mark.parametrize("valor", [None, "", "2026-08-31", "31/02/2026", "x"])
def test_vencimento_invalido_fica_ausente(valor):
    assert pix_recovery._parse_boleto_expiry_date(valor) == ""


def test_dados_boleto_nao_carregam_url_barcode_ou_pii_extra():
    assert pix_recovery._dados_boleto(payload_boleto()) == {
        "order_id": ORDER_ID,
        "email": "boleto@example.com",
        "expires_at": "2026-08-31T00:00:00+00:00",
    }


def test_boleto_confirma_server_to_server_antes_do_ledger(monkeypatch):
    eventos = []

    def confirmar(order_id, statuses_aceitos, payment_method_esperado=None):
        eventos.append(("confirm", payment_method_esperado, statuses_aceitos))
        return {
            "id": order_id,
            "status": "waiting_payment",
            "payment_method": "boleto",
            "email": "oficial@example.com",
            "first_name": "Maria",
        }

    monkeypatch.setattr(pix_recovery, "confirmar_venda_kiwify", confirmar)
    monkeypatch.setattr(
        pix_recovery,
        "adquirir_processamento",
        lambda *args: eventos.append(("acquire", args)) or True,
    )
    monkeypatch.setattr(pix_recovery, "transicionar", lambda *args: True)
    monkeypatch.setattr(pix_recovery, "_alterar_tag_boleto_kit", lambda *args: True)

    assert pix_recovery.processar_boleto_criado(payload_boleto()) is True
    assert eventos[0] == (
        "confirm",
        "boleto",
        pix_recovery.KIWIFY_PENDING_STATUSES,
    )
    assert eventos[1][0] == "acquire"
    assert eventos[1][1][3:] == (
        "boleto",
        "2026-08-31T00:00:00+00:00",
    )


@pytest.mark.parametrize("customer_key", ["customer", "Customer"])
def test_confirmacao_real_boleto_aceita_customer_variants(monkeypatch, customer_key):
    monkeypatch.setenv("KIWIFY_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(pix_recovery, "_obter_oauth_token_kiwify", lambda: "token")
    resposta = {
        "id": ORDER_ID,
        "status": "waiting_payment",
        "payment_method": "boleto",
        customer_key: {
            "email": "oficial@example.com",
            "first_name": "Maria de Souza",
            "name": "Ignorado",
            "full_name": "Tambem Ignorado",
        },
    }
    monkeypatch.setattr(
        pix_recovery.requests, "get", lambda *a, **k: FakeResponse(200, resposta)
    )
    confirmado = CONFIRMAR_VENDA_REAL(
        ORDER_ID, {"waiting_payment"}, payment_method_esperado="boleto"
    )
    assert confirmado["email"] == "oficial@example.com"
    assert confirmado["first_name"] == "Maria"


def test_confirmacao_invalida_nao_toca_ledger_kit(monkeypatch):
    efeitos = []
    monkeypatch.setattr(pix_recovery, "confirmar_venda_kiwify", lambda *a, **k: {})
    monkeypatch.setattr(
        pix_recovery, "adquirir_processamento", lambda *a: efeitos.append("ledger")
    )
    monkeypatch.setattr(
        pix_recovery, "_alterar_tag_boleto_kit", lambda *a: efeitos.append("kit")
    )
    monkeypatch.setattr(pix_recovery, "buscar_ledger", lambda *a: {})
    assert pix_recovery.processar_boleto_criado(payload_boleto()) is False
    assert efeitos == []


def test_subscribe_boleto_envia_first_name_no_mesmo_post_sem_put(monkeypatch):
    posts = []
    puts = []
    monkeypatch.setenv("TAG_BOLETO_ID", "tag-boleto")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda url, **kwargs: posts.append((url, kwargs)) or FakeResponse(201),
    )
    monkeypatch.setattr(
        pix_recovery.requests,
        "put",
        lambda *args, **kwargs: puts.append((args, kwargs)),
    )

    assert pix_recovery._alterar_tag_boleto_kit(
        "oficial@example.com", "subscribe", "Maria"
    ) is True
    assert posts == [
        (
            "https://api.convertkit.com/v3/tags/tag-boleto/subscribe",
            {
                "json": {
                    "api_secret": "secret",
                    "email": "oficial@example.com",
                    "first_name": "Maria",
                },
                "timeout": 5,
            },
        )
    ]
    assert puts == []


def test_config_boleto_ausente_falha_segura_sem_http(monkeypatch):
    chamadas = []
    monkeypatch.delenv("TAG_BOLETO_ID", raising=False)
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setattr(
        pix_recovery.requests, "post", lambda *a, **k: chamadas.append((a, k))
    )
    assert pix_recovery._alterar_tag_boleto_kit("x@example.com", "subscribe") is False
    assert chamadas == []


@pytest.mark.parametrize("resultado", [400, 500])
def test_kit_boleto_nao_2xx_nao_conclui(monkeypatch, resultado):
    transicoes = []
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *a: True)
    monkeypatch.setattr(
        pix_recovery,
        "transicionar",
        lambda oid, token, origem, destino: transicoes.append((origem, destino)) or True,
    )
    monkeypatch.setattr(
        pix_recovery, "_alterar_tag_boleto_kit", lambda *a: resultado < 300
    )
    monkeypatch.setattr(
        pix_recovery, "compensar_subscribe_boleto_concorrente", lambda *a: False
    )
    assert pix_recovery.processar_boleto_criado(payload_boleto()) is False
    assert ("subscribing", "completed") not in transicoes
    assert ("subscribing", "failed") in transicoes


def test_timeout_kit_boleto_fica_compensavel_retryable(monkeypatch):
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *a: True)
    monkeypatch.setattr(
        pix_recovery,
        "transicionar",
        lambda oid, token, origem, destino: (origem, destino)
        == ("processing", "subscribing"),
    )
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_boleto_kit",
        lambda *a: (_ for _ in ()).throw(TimeoutError("timeout")),
    )
    monkeypatch.setattr(
        pix_recovery, "compensar_subscribe_boleto_concorrente", lambda *a: False
    )
    assert pix_recovery.processar_boleto_criado(payload_boleto()) is False


def test_completed_somente_depois_do_subscribe_2xx(monkeypatch):
    eventos = []
    monkeypatch.setattr(pix_recovery, "adquirir_processamento", lambda *a: True)
    monkeypatch.setattr(
        pix_recovery,
        "transicionar",
        lambda oid, token, origem, destino: eventos.append((origem, destino)) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "_alterar_tag_boleto_kit",
        lambda *a: eventos.append("subscribe-2xx") or True,
    )
    assert pix_recovery.processar_boleto_criado(payload_boleto()) is True
    assert eventos == [
        ("processing", "subscribing"),
        "subscribe-2xx",
        ("subscribing", "completed"),
    ]


def test_wrapper_persiste_boleto_antes_do_handler_e_agenda(monkeypatch):
    eventos = []
    tarefas = BackgroundTasks()
    request = FakeRequest(payload_boleto())

    def enqueue(*args):
        eventos.append(("persisted", args))
        return True

    async def handler(req, background_tasks):
        eventos.append(("handler", None))
        return {"status": "processado"}

    monkeypatch.setattr(pix_recovery, "enfileirar_job_pix", enqueue)
    monkeypatch.setattr(pix_recovery, "webhook_kiwify", handler)
    resposta = asyncio.run(pix_recovery.webhook_kiwify_com_pix(request, tarefas))
    assert resposta == {"status": "processado"}
    assert eventos[0] == (
        "persisted",
        (ORDER_ID, "billet_created", "2026-08-31T00:00:00+00:00"),
    )
    assert eventos[1] == ("handler", None)
    assert tarefas.tasks[0].func is pix_recovery.processar_job_pix
    assert tarefas.tasks[0].args == (
        ORDER_ID,
        "billet_created",
        "2026-08-31T00:00:00+00:00",
    )


def test_paid_boleto_remove_somente_tag_boleto(monkeypatch):
    eventos = []
    monkeypatch.setattr(
        pix_recovery,
        "persistir_cancelamento_metodo",
        lambda *args: eventos.append(("persist", args)) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento_boleto",
        lambda *args: eventos.append(("boleto", args)) or True,
    )
    monkeypatch.setattr(
        pix_recovery,
        "reconciliar_cancelamento",
        lambda *args: eventos.append(("pix", args)) or True,
    )
    pago = payload_boleto(order_status="paid", webhook_event_type="order_approved")
    assert pix_recovery.cancelar_pix_por_pagamento(pago) is True
    assert [evento[0] for evento in eventos] == ["persist", "boleto"]


def test_unsubscribe_boleto_usa_tag_correta(monkeypatch):
    posts = []
    monkeypatch.setenv("TAG_BOLETO_ID", "tag-boleto")
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setattr(
        pix_recovery,
        "buscar_ledger",
        lambda *a: {
            "status": "cancelled_pending_unsubscribe",
            "email": "x@example.com",
            "subscribe_attempted": True,
        },
    )
    monkeypatch.setattr(
        pix_recovery.requests,
        "post",
        lambda url, **kwargs: posts.append(url) or FakeResponse(204),
    )
    assert pix_recovery.reconciliar_cancelamento_boleto(ORDER_ID) is True
    assert posts == ["https://api.convertkit.com/v3/tags/tag-boleto/unsubscribe"]


def test_falha_unsubscribe_boleto_permanece_pendente(monkeypatch):
    monkeypatch.setattr(
        pix_recovery,
        "buscar_ledger",
        lambda *a: {
            "status": "cancelled_pending_unsubscribe",
            "email": "x@example.com",
            "subscribe_attempted": True,
        },
    )
    monkeypatch.setattr(pix_recovery, "_alterar_tag_boleto_kit", lambda *a: False)
    assert pix_recovery.reconciliar_cancelamento_boleto(ORDER_ID) is False


def test_worker_boleto_retry_e_fencing_usa_job_existente(monkeypatch):
    eventos = []
    monkeypatch.setattr(pix_recovery, "uuid4", lambda: "job-token")
    monkeypatch.setattr(
        pix_recovery,
        "adquirir_job_pix",
        lambda *args: eventos.append(("acquire", args)) or True,
    )
    monkeypatch.setattr(pix_recovery, "processar_boleto_criado", lambda *a: False)
    monkeypatch.setattr(
        pix_recovery,
        "falhar_job_pix",
        lambda *args, **kwargs: eventos.append(("retry", args)) or True,
    )
    assert pix_recovery.processar_job_pix(
        ORDER_ID, "billet_created", "2026-08-31T00:00:00+00:00"
    ) is False
    assert eventos[0] == (
        "acquire",
        (ORDER_ID, "billet_created", "job-token"),
    )
    assert eventos[1][0] == "retry"
    assert eventos[1][1][2] == "job-token"


def test_dois_workers_boleto_tem_um_unico_vencedor(monkeypatch):
    aquisicoes = iter([True, False])
    efeitos = []
    monkeypatch.setattr(
        pix_recovery, "adquirir_job_pix", lambda *args: next(aquisicoes)
    )
    monkeypatch.setattr(
        pix_recovery,
        "processar_boleto_criado",
        lambda *args: efeitos.append("subscribe") or True,
    )
    monkeypatch.setattr(pix_recovery, "concluir_job_pix", lambda *args: True)
    assert pix_recovery.processar_job_pix(ORDER_ID, "billet_created") is True
    assert pix_recovery.processar_job_pix(ORDER_ID, "billet_created") is False
    assert efeitos == ["subscribe"]


def test_duplicate_boleto_converge_na_chave_existente():
    migration_jobs = (
        Path(__file__).parents[1] / "sql" / "007_create_recovery_pix_jobs.sql"
    ).read_text(encoding="utf-8").lower()
    migration_boleto = (
        Path(__file__).parents[1] / "sql" / "010_add_boleto_recovery.sql"
    ).read_text(encoding="utf-8").lower()
    assert "primary key (order_id, event_type)" in migration_jobs
    assert "billet_created" in migration_boleto
    assert "updated_at < now() - make_interval" in migration_jobs
    assert "and attempt_token = p_attempt_token" in migration_jobs


def test_reconciler_preserva_expiry_sem_timer(monkeypatch):
    processados = []
    monkeypatch.setattr(
        pix_recovery,
        "listar_jobs_pix_recuperaveis",
        lambda limit: [
            {
                "order_id": ORDER_ID,
                "event_type": "billet_created",
                "expires_at": "2026-08-31T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(
        pix_recovery,
        "processar_job_pix",
        lambda *args: processados.append(args) or True,
    )
    assert pix_recovery.reconciliar_jobs_pix() == {
        "candidates": 1,
        "completed": 1,
        "attempted": 1,
    }
    assert processados == [
        (ORDER_ID, "billet_created", "2026-08-31T00:00:00+00:00")
    ]


def test_migration_010_generaliza_sem_tabela_duplicada_e_preserva_view_pix():
    sql = (
        Path(__file__).parents[1] / "sql" / "010_add_boleto_recovery.sql"
    ).read_text(encoding="utf-8").lower()
    normalized = " ".join(sql.split())
    assert "add column if not exists payment_method text" in normalized
    assert "add column if not exists expires_at timestamptz" in normalized
    assert "'pix_created', 'billet_created', 'paid'" in normalized
    assert "primary key" not in normalized
    assert "create table" not in normalized
    assert "create or replace view public.recovery_payment_attribution" in normalized
    assert "public.recovery_pix_attribution e deliberadamente preservada" in normalized
    assert "paid_confirmed_at >= recovery_completed_at" in normalized
    assert "coalesce(recovery_completed_at, now())" in normalized
    assert "coalesce(p_payment_method, 'pix')" in normalized
    assert "security definer" in normalized
    assert "security_invoker = true" in normalized
    assert "from public, anon, authenticated" in normalized
    assert "to service_role" in normalized


def test_migration_nao_persiste_barcode_url_nem_automatiza_expiracao():
    sql = (
        Path(__file__).parents[1] / "sql" / "010_add_boleto_recovery.sql"
    ).read_text(encoding="utf-8").lower()
    assert "boleto_barcode" not in sql
    assert "boleto_url" not in sql
    assert "pg_cron" not in sql
    assert "sleep" not in sql
    assert "expiry_job" not in sql
