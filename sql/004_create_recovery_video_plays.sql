create table if not exists public.recovery_video_plays (
    id uuid primary key default gen_random_uuid(),
    manychat_id text not null unique,
    status text not null check (status in ('processing', 'completed', 'failed')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_recovery_video_plays_processing_updated_at
    on public.recovery_video_plays (updated_at)
    where status = 'processing';

create or replace function public.touch_recovery_video_plays_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists trg_touch_recovery_video_plays_updated_at
on public.recovery_video_plays;

create trigger trg_touch_recovery_video_plays_updated_at
before update on public.recovery_video_plays
for each row
execute function public.touch_recovery_video_plays_updated_at();
