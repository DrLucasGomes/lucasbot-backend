create table if not exists public.recovery_pix_jobs (
    order_id text not null,
    event_type text not null
        check (event_type in ('pix_created', 'paid')),
    status text not null default 'pending'
        check (status in ('pending', 'processing', 'retryable', 'failed', 'completed')),
    attempts integer not null default 0 check (attempts >= 0),
    attempt_token text,
    processing_started_at timestamptz,
    last_attempt_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (order_id, event_type)
);

drop trigger if exists trg_recovery_pix_jobs_updated_at
    on public.recovery_pix_jobs;

create trigger trg_recovery_pix_jobs_updated_at
before update on public.recovery_pix_jobs
for each row
execute function public.set_recovery_pix_orders_updated_at();

create index if not exists idx_recovery_pix_jobs_recovery
    on public.recovery_pix_jobs (status, updated_at);

revoke all on table public.recovery_pix_jobs from public, anon, authenticated;
grant select, insert, update on table public.recovery_pix_jobs to service_role;

create or replace function public.recovery_pix_job_enqueue(
    p_order_id text,
    p_event_type text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if p_order_id is null or btrim(p_order_id) = ''
       or p_event_type not in ('pix_created', 'paid') then
        return false;
    end if;

    insert into public.recovery_pix_jobs (order_id, event_type)
    values (btrim(p_order_id), p_event_type)
    on conflict (order_id, event_type) do update
       set status = 'pending'
     where excluded.event_type = 'paid'
       and public.recovery_pix_jobs.status = 'completed';

    return exists (
        select 1
          from public.recovery_pix_jobs
         where order_id = btrim(p_order_id)
           and event_type = p_event_type
    );
end;
$$;

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
       or p_event_type not in ('pix_created', 'paid')
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
                and updated_at < now() - make_interval(mins => greatest(p_stale_minutes, 1))
            )
       );

    get diagnostics affected = row_count;
    return affected = 1;
end;
$$;

create or replace function public.recovery_pix_job_complete(
    p_order_id text,
    p_event_type text,
    p_attempt_token text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    affected integer := 0;
begin
    update public.recovery_pix_jobs
       set status = 'completed'
     where order_id = p_order_id
       and event_type = p_event_type
       and attempt_token = p_attempt_token
       and status = 'processing';

    get diagnostics affected = row_count;
    return affected = 1;
end;
$$;

create or replace function public.recovery_pix_job_fail(
    p_order_id text,
    p_event_type text,
    p_attempt_token text,
    p_retryable boolean default true
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    affected integer := 0;
begin
    update public.recovery_pix_jobs
       set status = case when p_retryable then 'retryable' else 'failed' end
     where order_id = p_order_id
       and event_type = p_event_type
       and attempt_token = p_attempt_token
       and status = 'processing';

    get diagnostics affected = row_count;
    return affected = 1;
end;
$$;

revoke execute on function public.recovery_pix_job_enqueue(text, text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_job_acquire(text, text, text, integer) from public, anon, authenticated;
revoke execute on function public.recovery_pix_job_complete(text, text, text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_job_fail(text, text, text, boolean) from public, anon, authenticated;

grant execute on function public.recovery_pix_job_enqueue(text, text) to service_role;
grant execute on function public.recovery_pix_job_acquire(text, text, text, integer) to service_role;
grant execute on function public.recovery_pix_job_complete(text, text, text) to service_role;
grant execute on function public.recovery_pix_job_fail(text, text, text, boolean) to service_role;
