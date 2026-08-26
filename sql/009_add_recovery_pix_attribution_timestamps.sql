-- Atribuicao temporal minima no ledger durable existente.
-- Nao ha backfill: a medicao confiavel comeca na aplicacao desta migration.

alter table if exists public.recovery_pix_orders
    add column if not exists recovery_completed_at timestamptz;
alter table if exists public.recovery_pix_orders
    add column if not exists paid_confirmed_at timestamptz;

create or replace function public.preserve_recovery_pix_attribution_timestamps()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
    if old.recovery_completed_at is not null
       and new.recovery_completed_at is distinct from old.recovery_completed_at then
        raise exception 'recovery_completed_at is write-once';
    end if;
    if old.paid_confirmed_at is not null
       and new.paid_confirmed_at is distinct from old.paid_confirmed_at then
        raise exception 'paid_confirmed_at is write-once';
    end if;
    return new;
end;
$$;

drop trigger if exists trg_preserve_recovery_pix_attribution_timestamps
    on public.recovery_pix_orders;
create trigger trg_preserve_recovery_pix_attribution_timestamps
before update on public.recovery_pix_orders
for each row execute function public.preserve_recovery_pix_attribution_timestamps();

create or replace function public.recovery_pix_transition(
    p_order_id text, p_attempt_token text, p_from_status text, p_to_status text
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

create or replace function public.recovery_pix_cancel(
    p_order_id text, p_email text default null
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if p_order_id is null or btrim(p_order_id) = '' then
        return false;
    end if;
    insert into public.recovery_pix_orders (
        order_id, email, status, paid_confirmed_at
    ) values (
        p_order_id, nullif(btrim(coalesce(p_email, '')), ''),
        'cancelled_pending_unsubscribe', now()
    )
    on conflict (order_id) do update
       set status = case
               when public.recovery_pix_orders.status = 'cancelled'
                    and public.recovery_pix_orders.subscribe_attempted = false
                   then 'cancelled'
               else 'cancelled_pending_unsubscribe'
           end,
           email = coalesce(excluded.email, public.recovery_pix_orders.email),
           paid_confirmed_at = coalesce(
               public.recovery_pix_orders.paid_confirmed_at,
               excluded.paid_confirmed_at
           );
    return true;
end;
$$;

create or replace view public.recovery_pix_attribution
with (security_invoker = true)
as
select
    order_id,
    recovery_completed_at,
    paid_confirmed_at,
    (recovery_completed_at is not null and paid_confirmed_at is not null
     and paid_confirmed_at >= recovery_completed_at) as recovery_conversion,
    case
        when recovery_completed_at is not null and paid_confirmed_at is not null
         and paid_confirmed_at >= recovery_completed_at
        then extract(epoch from (paid_confirmed_at - recovery_completed_at))
        else null
    end as conversion_delay_seconds
from public.recovery_pix_orders;

alter table public.recovery_pix_orders enable row level security;
revoke all on table public.recovery_pix_orders from public, anon, authenticated;
revoke all on table public.recovery_pix_orders from service_role;
grant select on table public.recovery_pix_orders to service_role;

revoke execute on function public.preserve_recovery_pix_attribution_timestamps()
    from public, anon, authenticated;
revoke execute on function public.recovery_pix_transition(text, text, text, text)
    from public, anon, authenticated;
revoke execute on function public.recovery_pix_cancel(text, text)
    from public, anon, authenticated;
grant execute on function public.recovery_pix_transition(text, text, text, text)
    to service_role;
grant execute on function public.recovery_pix_cancel(text, text) to service_role;

revoke all on table public.recovery_pix_attribution from public, anon, authenticated;
grant select on table public.recovery_pix_attribution to service_role;
