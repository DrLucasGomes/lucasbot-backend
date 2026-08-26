create extension if not exists pgcrypto;

create table if not exists public.recovery_pix_attribution_events (
    id uuid primary key default gen_random_uuid(),
    order_id text not null,
    event_name text not null check (event_name in (
        'recovery_entered',
        'purchase_completed'
    )),
    dedupe_key text not null unique,
    occurred_at timestamptz not null default now()
);

create index if not exists idx_recovery_pix_attribution_order_occurred
    on public.recovery_pix_attribution_events (order_id, occurred_at);

create index if not exists idx_recovery_pix_attribution_event_occurred
    on public.recovery_pix_attribution_events (event_name, occurred_at);

create or replace function public.prevent_update_delete_recovery_pix_attribution_events()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    raise exception 'recovery_pix_attribution_events is append-only';
end;
$$;

drop trigger if exists trg_prevent_update_delete_recovery_pix_attribution_events
    on public.recovery_pix_attribution_events;

create trigger trg_prevent_update_delete_recovery_pix_attribution_events
before update or delete on public.recovery_pix_attribution_events
for each row
execute function public.prevent_update_delete_recovery_pix_attribution_events();

alter table public.recovery_pix_attribution_events enable row level security;

revoke all on table public.recovery_pix_attribution_events
    from public, anon, authenticated;
grant select, insert on table public.recovery_pix_attribution_events
    to service_role;

create or replace view public.recovery_pix_attribution
with (security_invoker = true)
as
with events_by_order as (
    select
        order_id,
        min(occurred_at) filter (
            where event_name = 'recovery_entered'
        ) as recovery_pix_entered_at,
        min(occurred_at) filter (
            where event_name = 'purchase_completed'
        ) as purchase_completed_at
    from public.recovery_pix_attribution_events
    group by order_id
)
select
    order_id,
    recovery_pix_entered_at,
    purchase_completed_at,
    (
        recovery_pix_entered_at is not null
        and purchase_completed_at is not null
        and purchase_completed_at >= recovery_pix_entered_at
    ) as recovery_conversion,
    case
        when recovery_pix_entered_at is not null
         and purchase_completed_at is not null
         and purchase_completed_at >= recovery_pix_entered_at
        then extract(epoch from (purchase_completed_at - recovery_pix_entered_at))
        else null
    end as conversion_delay_seconds
from events_by_order;

revoke all on table public.recovery_pix_attribution
    from public, anon, authenticated;
grant select on table public.recovery_pix_attribution to service_role;
