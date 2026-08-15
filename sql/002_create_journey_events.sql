create extension if not exists pgcrypto;

create table if not exists public.journey_events (
    id uuid primary key default gen_random_uuid(),
    lead_id uuid null,
    manychat_id text not null,
    event_name text not null check (event_name in (
        'step_started',
        'step_answered',
        'fallback_triggered',
        'email_captured',
        'offer_clicked',
        'checkout_started',
        'purchase'
    )),
    event_stage text null,
    event_value text null,
    source_system text not null,
    dedupe_key text not null unique,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_journey_events_manychat_created_at
    on public.journey_events (manychat_id, created_at);

create or replace function public.prevent_update_delete_journey_events()
returns trigger
language plpgsql
as $$
begin
    raise exception 'journey_events is append-only';
end;
$$;

drop trigger if exists trg_prevent_update_delete_journey_events on public.journey_events;

create trigger trg_prevent_update_delete_journey_events
before update or delete on public.journey_events
for each row
execute function public.prevent_update_delete_journey_events();
