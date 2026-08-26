-- Fase 1 da recuperacao durable de boleto.
-- O vencimento e apenas tecnico: esta migration nao agenda nem executa expiracao.

alter table public.recovery_pix_orders
    add column if not exists payment_method text;
alter table public.recovery_pix_orders
    add column if not exists expires_at timestamptz;
alter table public.recovery_pix_orders
    drop constraint if exists recovery_pix_orders_payment_method_check;
alter table public.recovery_pix_orders
    add constraint recovery_pix_orders_payment_method_check
    check (payment_method is null or payment_method in ('pix', 'boleto'));

alter table public.recovery_pix_jobs
    add column if not exists expires_at timestamptz;
alter table public.recovery_pix_jobs
    drop constraint if exists recovery_pix_jobs_event_type_check;
alter table public.recovery_pix_jobs
    add constraint recovery_pix_jobs_event_type_check
    check (event_type in ('pix_created', 'billet_created', 'paid'));

drop function if exists public.recovery_pix_job_enqueue(text, text);
create or replace function public.recovery_pix_job_enqueue(
    p_order_id text,
    p_event_type text,
    p_expires_at timestamptz default null
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if p_order_id is null or btrim(p_order_id) = ''
       or p_event_type not in ('pix_created', 'billet_created', 'paid') then
        return false;
    end if;

    insert into public.recovery_pix_jobs (order_id, event_type, expires_at)
    values (btrim(p_order_id), p_event_type, p_expires_at)
    on conflict (order_id, event_type) do update
       set status = 'pending',
           expires_at = coalesce(
               public.recovery_pix_jobs.expires_at,
               excluded.expires_at
           )
     where excluded.event_type = 'paid'
       and public.recovery_pix_jobs.status = 'completed';

    return exists (
        select 1 from public.recovery_pix_jobs
         where order_id = btrim(p_order_id)
           and event_type = p_event_type
    );
end;
$$;

drop function if exists public.recovery_pix_acquire(text, text, text, integer);
create or replace function public.recovery_pix_acquire(
    p_order_id text,
    p_email text,
    p_attempt_token text,
    p_stale_minutes integer default 5,
    p_payment_method text default null,
    p_expires_at timestamptz default null
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
       or p_email is null or btrim(p_email) = ''
       or p_attempt_token is null or btrim(p_attempt_token) = ''
       or (p_payment_method is not null and p_payment_method not in ('pix', 'boleto')) then
        return false;
    end if;

    insert into public.recovery_pix_orders (
        order_id, email, status, attempt_token, processing_started_at,
        payment_method, expires_at
    ) values (
        p_order_id, p_email, 'processing', p_attempt_token, now(),
        coalesce(p_payment_method, 'pix'), p_expires_at
    )
    on conflict (order_id) do nothing;

    get diagnostics affected = row_count;
    if affected = 1 then
        return true;
    end if;

    update public.recovery_pix_orders
       set status = 'processing',
           email = coalesce(nullif(btrim(p_email), ''), email),
           attempt_token = p_attempt_token,
           processing_started_at = now(),
           payment_method = coalesce(payment_method, p_payment_method, 'pix'),
           expires_at = coalesce(expires_at, p_expires_at)
     where order_id = p_order_id
       and (payment_method is null or p_payment_method is null
            or payment_method = p_payment_method)
       and (
            status = 'failed'
            or (status in ('processing', 'subscribing')
                and updated_at < now() - make_interval(
                    mins => greatest(p_stale_minutes, 1)
                ))
       );

    get diagnostics affected = row_count;
    return affected = 1;
end;
$$;

create or replace function public.recovery_pix_transition(
    p_order_id text,
    p_attempt_token text,
    p_from_status text,
    p_to_status text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    affected integer := 0;
begin
    if not (
        (p_from_status = 'processing' and p_to_status = 'subscribing')
        or (p_from_status = 'subscribing' and p_to_status = 'completed')
        or (p_from_status = 'subscribing' and p_to_status = 'failed')
    ) then
        return false;
    end if;

    update public.recovery_pix_orders
       set status = p_to_status,
           subscribe_attempted = case
               when p_from_status = 'processing' and p_to_status = 'subscribing'
                   then true else subscribe_attempted
           end,
           processing_started_at = case
               when p_to_status = 'subscribing' then now()
               else processing_started_at
           end,
           recovery_completed_at = case
               when p_from_status = 'subscribing' and p_to_status = 'completed'
                   then coalesce(recovery_completed_at, now())
               else recovery_completed_at
           end
     where order_id = p_order_id
       and attempt_token = p_attempt_token
       and status = p_from_status;

    get diagnostics affected = row_count;
    return affected = 1;
end;
$$;

drop function if exists public.recovery_pix_cancel(text, text);
create or replace function public.recovery_pix_cancel(
    p_order_id text,
    p_email text default null,
    p_payment_method text default null
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if p_order_id is null or btrim(p_order_id) = ''
       or (p_payment_method is not null and p_payment_method not in ('pix', 'boleto')) then
        return false;
    end if;

    insert into public.recovery_pix_orders (
        order_id, email, status, paid_confirmed_at, payment_method
    ) values (
        p_order_id,
        nullif(btrim(coalesce(p_email, '')), ''),
        'cancelled_pending_unsubscribe',
        now(),
        p_payment_method
    )
    on conflict (order_id) do update
       set status = case
               when public.recovery_pix_orders.status = 'cancelled'
                    and public.recovery_pix_orders.subscribe_attempted = false
                   then 'cancelled'
               else 'cancelled_pending_unsubscribe'
           end,
           email = coalesce(excluded.email, public.recovery_pix_orders.email),
           payment_method = coalesce(
               public.recovery_pix_orders.payment_method,
               excluded.payment_method
           ),
           paid_confirmed_at = coalesce(
               public.recovery_pix_orders.paid_confirmed_at,
               excluded.paid_confirmed_at
           )
     where public.recovery_pix_orders.payment_method is null
        or excluded.payment_method is null
        or public.recovery_pix_orders.payment_method = excluded.payment_method;

    return exists (
        select 1 from public.recovery_pix_orders
         where order_id = p_order_id
           and (payment_method is null or p_payment_method is null
                or payment_method = p_payment_method)
    );
end;
$$;

create or replace view public.recovery_payment_attribution
with (security_invoker = true)
as
select
    order_id,
    payment_method,
    recovery_completed_at,
    paid_confirmed_at,
    (recovery_completed_at is not null and paid_confirmed_at is not null
     and paid_confirmed_at >= recovery_completed_at) as recovery_conversion,
    case
        when recovery_completed_at is not null and paid_confirmed_at is not null
         and paid_confirmed_at >= recovery_completed_at
        then extract(epoch from (paid_confirmed_at - recovery_completed_at))
        else null
    end as conversion_delay_seconds,
    expires_at
from public.recovery_pix_orders;

alter table public.recovery_pix_orders enable row level security;
alter table public.recovery_pix_jobs enable row level security;
revoke all on table public.recovery_pix_orders from public, anon, authenticated;
revoke all on table public.recovery_pix_jobs from public, anon, authenticated;
revoke all on table public.recovery_pix_orders from service_role;
revoke all on table public.recovery_pix_jobs from service_role;
grant select on table public.recovery_pix_orders to service_role;
grant select on table public.recovery_pix_jobs to service_role;

revoke execute on function public.recovery_pix_job_enqueue(text, text, timestamptz)
    from public, anon, authenticated;
revoke execute on function public.recovery_pix_acquire(
    text, text, text, integer, text, timestamptz
) from public, anon, authenticated;
revoke execute on function public.recovery_pix_transition(text, text, text, text)
    from public, anon, authenticated;
revoke execute on function public.recovery_pix_cancel(text, text, text)
    from public, anon, authenticated;
grant execute on function public.recovery_pix_job_enqueue(text, text, timestamptz)
    to service_role;
grant execute on function public.recovery_pix_acquire(
    text, text, text, integer, text, timestamptz
) to service_role;
grant execute on function public.recovery_pix_transition(text, text, text, text)
    to service_role;
grant execute on function public.recovery_pix_cancel(text, text, text)
    to service_role;

revoke all on table public.recovery_payment_attribution
    from public, anon, authenticated;
grant select on table public.recovery_payment_attribution to service_role;

-- public.recovery_pix_attribution e deliberadamente preservada sem alteracao.
