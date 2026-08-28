begin;

create table if not exists public.click_sessions (
    token text primary key,
    origem text not null,
    campanha text,
    video text,
    produto text,
    utm_source text,
    utm_medium text,
    utm_campaign text,
    utm_content text,
    utm_term text,
    manychat_id text,
    lead_id text,
    claimed boolean not null default false,
    claim_method text,
    claim_confidence text,
    user_agent text,
    ip_hash text,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    claimed_at timestamptz
);

create index if not exists idx_click_sessions_created_at
    on public.click_sessions (created_at desc);

create index if not exists idx_click_sessions_unclaimed_recent
    on public.click_sessions (created_at desc)
    where claimed = false;

create index if not exists idx_click_sessions_expires_at
    on public.click_sessions (expires_at);

create index if not exists idx_click_sessions_utm_content
    on public.click_sessions (utm_content);

create index if not exists idx_click_sessions_manychat_id
    on public.click_sessions (manychat_id);

alter table public.click_sessions enable row level security;

revoke all on table public.click_sessions from anon;
revoke all on table public.click_sessions from authenticated;

grant select, insert, update, delete on table public.click_sessions to service_role;

commit;
