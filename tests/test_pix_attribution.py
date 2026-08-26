from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "009_add_recovery_pix_attribution_timestamps.sql"
).read_text(encoding="utf-8").lower()
SQL = " ".join(MIGRATION.split())


def test_migration_adiciona_somente_timestamps_no_ledger_existente():
    assert "add column if not exists recovery_completed_at timestamptz" in SQL
    assert "add column if not exists paid_confirmed_at timestamptz" in SQL
    assert "create table" not in SQL
    assert "attribution_events" not in SQL
    assert "dedupe_key" not in SQL
    assert "event_name" not in SQL


def test_recovery_timestamp_so_na_transicao_fenced_completed():
    assert "p_from_status = 'subscribing' and p_to_status = 'completed'" in SQL
    assert "then coalesce(recovery_completed_at, now())" in SQL
    assert "and attempt_token = p_attempt_token" in SQL
    assert "and status = p_from_status" in SQL
    assert SQL.count("then coalesce(recovery_completed_at, now())") == 1


def test_subscribe_falhou_ou_cancelled_nao_preenchem_recovery_timestamp():
    assignment = SQL.split("recovery_completed_at = case", 1)[1].split("end", 1)[0]
    assert "subscribing' and p_to_status = 'completed" in assignment
    assert "failed" not in assignment
    assert "cancelled" not in assignment
    assert "else recovery_completed_at" in assignment


def test_paid_timestamp_eh_atomico_na_rpc_durable_e_write_once():
    cancel_rpc = SQL.split(
        "create or replace function public.recovery_pix_cancel", 1
    )[1]
    assert "paid_confirmed_at" in cancel_rpc
    assert "paid_confirmed_at = coalesce(" in cancel_rpc
    assert "public.recovery_pix_orders.paid_confirmed_at" in cancel_rpc
    assert "excluded.paid_confirmed_at" in cancel_rpc


def test_timestamps_nao_podem_ser_removidos_nem_sobrescritos():
    assert "old.recovery_completed_at is not null" in SQL
    assert "new.recovery_completed_at is distinct from old.recovery_completed_at" in SQL
    assert "old.paid_confirmed_at is not null" in SQL
    assert "new.paid_confirmed_at is distinct from old.paid_confirmed_at" in SQL
    assert "before update on public.recovery_pix_orders" in SQL


def test_view_define_conversao_e_delay_sem_negativo():
    assert "create or replace view public.recovery_pix_attribution" in SQL
    assert "paid_confirmed_at >= recovery_completed_at" in SQL
    assert "extract(epoch from (paid_confirmed_at - recovery_completed_at))" in SQL
    assert "else null" in SQL


def test_casos_matematicos_da_view():
    def derive(recovery, paid):
        conversion = recovery is not None and paid is not None and paid >= recovery
        delay = paid - recovery if conversion else None
        return conversion, delay

    assert derive(10, 40) == (True, 30)
    assert derive(None, 40) == (False, None)
    assert derive(10, None) == (False, None)
    assert derive(10, 10) == (True, 0)
    assert derive(40, 10) == (False, None)


def test_migration_idempotente_sem_backfill_inventado():
    assert SQL.count("add column if not exists") == 2
    assert "create or replace function" in SQL
    assert "drop trigger if exists" in SQL
    assert "create or replace view" in SQL
    assert "update public.recovery_pix_orders set recovery_completed_at" not in SQL
    assert "update public.recovery_pix_orders set paid_confirmed_at" not in SQL
    assert "created_at" not in SQL
    assert "updated_at" not in SQL


def test_rls_grants_e_security_invoker_seguem_hardening():
    assert "enable row level security" in SQL
    assert "security definer" in SQL
    assert "set search_path = pg_catalog, public" in SQL
    assert "with (security_invoker = true)" in SQL
    assert "from public, anon, authenticated" in SQL
    assert "grant select on table public.recovery_pix_orders to service_role" in SQL
    assert "grant select on table public.recovery_pix_attribution to service_role" in SQL
    assert "grant execute on function public.recovery_pix_transition" in SQL
    assert "grant execute on function public.recovery_pix_cancel" in SQL
    assert "grant insert" not in SQL
    assert "grant update" not in SQL


def test_migration_nao_contem_pii_nova_nem_touch_de_email():
    for forbidden in (
        "first_name",
        "phone",
        "telefone",
        "email_sent",
        "email_clicked",
        "last_touch",
    ):
        assert forbidden not in SQL
