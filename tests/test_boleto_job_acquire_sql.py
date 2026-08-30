from pathlib import Path


def test_migration_011_allows_billet_created_job_acquire():
    sql = Path("sql/011_fix_boleto_job_acquire.sql").read_text(encoding="utf-8")

    assert "recovery_pix_job_acquire" in sql
    assert "('pix_created', 'billet_created', 'paid')" in sql
    assert "status in ('pending', 'retryable')" in sql
    assert "attempts = attempts + 1" in sql
    assert "attempt_token = p_attempt_token" in sql
    assert "grant execute on function public.recovery_pix_job_acquire" in sql
