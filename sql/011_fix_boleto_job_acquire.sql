-- Hotfix: migration 010 ampliou enqueue/constraint para boleto, mas a RPC de
-- aquisicao criada na 007 ainda aceitava apenas pix_created/paid.
-- Mantem a mesma state machine/fencing e apenas inclui billet_created.

create or replace function public.recovery_pix_job_acquire(
    p_order_id text,
    p_event_type text,
    p_attempt_token text,
    p_stale_minutes integer default 5
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    affected integer := 0;
begin
    if p_order_id is null or btrim(p_order_id) = ''
       or p_event_type not in ('pix_created', 'billet_created', 'paid')
       or p_attempt_token is null or btrim(p_attempt_token) = '' then
        return false;
    end if;

    update public.recovery_pix_jobs
       set status = 'processing',
           attempt_token = p_attempt_token,
           attempts = attempts + 1,
           processing_started_at = now(),
           last_attempt_at = now()
     where order_id = btrim(p_order_id)
       and event_type = p_event_type
       and (
            status in ('pending', 'retryable')
            or (
                status = 'processing'
                and updated_at < now() - make_interval(
                    mins => greatest(p_stale_minutes, 1)
                )
            )
       );

    get diagnostics affected = row_count;
    return affected = 1;
end;
$$;

revoke execute on function public.recovery_pix_job_acquire(text, text, text, integer)
    from public, anon, authenticated;
grant execute on function public.recovery_pix_job_acquire(text, text, text, integer)
    to service_role;
