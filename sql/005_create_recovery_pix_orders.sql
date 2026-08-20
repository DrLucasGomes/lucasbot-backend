create table if not exists public.recovery_pix_orders (
    order_id text primary key,
    email text,
    status text not null default 'processing'
        check (status in ('processing', 'subscribing', 'completed', 'failed', 'cancelled')),
    processing_started_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create or replace function public.set_recovery_pix_orders_updated_at()
returns trigger
language plpgsql
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

-- Adquire uma ordem PIX nova ou recupera uma tentativa falha/stale.
-- cancelled e completed sao terminais e nunca podem ser readquiridos.
create or replace function public.recovery_pix_acquire(
    p_order_id text,
    p_email text,
    p_stale_minutes integer default 5
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    affected integer := 0;
begin
    if p_order_id is null or btrim(p_order_id) = '' or p_email is null or btrim(p_email) = '' then
        return false;
    end if;

    insert into public.recovery_pix_orders (
        order_id, email, status, processing_started_at
    ) values (
        p_order_id, p_email, 'processing', now()
    )
    on conflict (order_id) do nothing;

    get diagnostics affected = row_count;
    if affected = 1 then
        return true;
    end if;

    update public.recovery_pix_orders
       set status = 'processing',
           email = coalesce(nullif(btrim(p_email), ''), email),
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

-- Compare-and-set de estado. Evita que completed/failed sobrescrevam cancelled.
create or replace function public.recovery_pix_transition(
    p_order_id text,
    p_from_status text,
    p_to_status text
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    affected integer := 0;
begin
    if p_from_status not in ('processing', 'subscribing')
       or p_to_status not in ('subscribing', 'completed', 'failed') then
        return false;
    end if;

    update public.recovery_pix_orders
       set status = p_to_status,
           processing_started_at = case
               when p_to_status = 'subscribing' then now()
               else processing_started_at
           end
     where order_id = p_order_id
       and status = p_from_status;

    get diagnostics affected = row_count;
    return affected = 1;
end;
$$;

-- Pagamento cria tombstone cancelled mesmo que pix_created ainda nao tenha chegado.
-- cancelled e terminal e impede qualquer aquisicao posterior da mesma order_id.
create or replace function public.recovery_pix_cancel(
    p_order_id text,
    p_email text default null
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
    if p_order_id is null or btrim(p_order_id) = '' then
        return false;
    end if;

    insert into public.recovery_pix_orders (order_id, email, status)
    values (p_order_id, nullif(btrim(coalesce(p_email, '')), ''), 'cancelled')
    on conflict (order_id) do update
       set status = 'cancelled',
           email = coalesce(excluded.email, public.recovery_pix_orders.email);

    return true;
end;
$$;
