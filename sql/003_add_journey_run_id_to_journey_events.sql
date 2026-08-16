alter table public.journey_events
    add column if not exists journey_run_id uuid null;

create index if not exists idx_journey_events_manychat_run_created_at
    on public.journey_events (manychat_id, journey_run_id, created_at);
