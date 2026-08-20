create table if not exists public.recovery_pix_orders (
    order_id text primary key,
    order_ref text,
    email text not null,
    status text not null default 'processing'
        check (status in ('processing', 'completed', 'failed', 'cancelled')),
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
