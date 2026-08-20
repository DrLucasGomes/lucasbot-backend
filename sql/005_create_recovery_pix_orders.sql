create table if not exists public.recovery_pix_orders (
    order_id text primary key,
    email text,
    status text not null default 'processing'
        check (status in (
            'processing',
            'subscribing',
            'completed',
            'failed',
            'cancelled_pending_unsubscribe',
            'cancelled'
        )),
    attempt_token text,
    processing_started_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create or replace function public.set_recovery_pix_orders_updated_at()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_recovery_pix_orders_updated_at
    on public.recovery_pix_orders;

create trigger trg_recovery_pix_orders_updated_at
before update on public.recovery_pix_orders
for each row
execute function public.set_recovery_pix_orders_updated_at();

create index if not exists idx_recovery_pix_orders_email
    on public.recovery_pix_orders (email);

create index if not exists idx_recovery_pix_orders_status
    on public.recovery_pix_orders (status);

create or replace function public.recovery_pix_acquire(
    p_order_id text,
    p_email text,
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
       or p_email is null or btrim(p_email) = ''
       or p_attempt_token is null or btrim(p_attempt_token) = '' then
        return false;
    end if;

    insert into public.recovery_pix_orders (
        order_id, email, status, attempt_token, processing_started_at
    ) values (
        p_order_id, p_email, 'processing', p_attempt_token, now()
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
           processing_started_at = now()
     where order_id = p_order_id
       and (
            status = 'failed'
            or (
                status in ('processing', 'subscribing')
                and updated_at < now() - make_interval(mins => greatest(p_stale_minutes, 1))
            )
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
           processing_started_at = case
               when p_to_status = 'subscribing' then now()
               else processing_started_at
           end
     where order_id = p_order_id
       and attempt_token = p_attempt_token
       and status = p_from_status;

    get diagnostics affected = row_count;
    return affected = 1;
end;
$$;

create or replace function public.recovery_pix_cancel(
    p_order_id text,
    p_email text default null
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

    insert into public.recovery_pix_orders (order_id, email, status)
    values (
        p_order_id,
        nullif(btrim(coalesce(p_email, '')), ''),
        'cancelled_pending_unsubscribe'
    )
    on conflict (order_id) do update
       set status = case
               when public.recovery_pix_orders.status = 'cancelled'
                   then 'cancelled'
               else 'cancelled_pending_unsubscribe'
           end,
           email = coalesce(excluded.email, public.recovery_pix_orders.email);

    return true;
end;
$$;

-- Um worker que efetivamente tentou subscribe pode reabrir um cancelled para
-- pending apenas se ainda possui o fencing token daquela tentativa.
create or replace function public.recovery_pix_reopen_cancel(
    p_order_id text,
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
    update public.recovery_pix_orders
       set status = 'cancelled_pending_unsubscribe'
     where order_id = p_order_id
       and attempt_token = p_attempt_token
       and status in ('cancelled', 'cancelled_pending_unsubscribe');

    get diagnostics affected = row_count;
    return affected = 1;
end;
$$;

create or replace function public.recovery_pix_confirm_cancel(
    p_order_id text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    affected integer := 0;
begin
    update public.recovery_pix_orders
       set status = 'cancelled'
     where order_id = p_order_id
       and status = 'cancelled_pending_unsubscribe';

    get diagnostics affected = row_count;
    if affected = 1 then
        return true;
    end if;

    return exists (
        select 1
          from public.recovery_pix_orders
         where order_id = p_order_id
           and status = 'cancelled'
    );
end;
$$;

revoke execute on function public.recovery_pix_acquire(text, text, text, integer) from public, anon, authenticated;
revoke execute on function public.recovery_pix_transition(text, text, text, text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_cancel(text, text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_reopen_cancel(text, text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_confirm_cancel(text) from public, anon, authenticated;

grant execute on function public.recovery_pix_acquire(text, text, text, integer) to service_role;
grant execute on function public.recovery_pix_transition(text, text, text, text) to service_role;
grant execute on function public.recovery_pix_cancel(text, text) to service_role;
grant execute on function public.recovery_pix_reopen_cancel(text, text) to service_role;
grant execute on function public.recovery_pix_confirm_cancel(text) to service_role;
