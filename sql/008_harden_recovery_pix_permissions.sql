-- Hardening incremental para ambientes onde 005/006/007 ja foram aplicadas.
-- Leitura direta e necessaria apenas pelo backend service_role; mutacoes ficam
-- restritas as RPCs SECURITY DEFINER com fencing/CAS.

alter table if exists public.recovery_pix_orders enable row level security;
alter table if exists public.recovery_pix_jobs enable row level security;

revoke all on table public.recovery_pix_orders from public, anon, authenticated;
revoke all on table public.recovery_pix_jobs from public, anon, authenticated;
revoke all on table public.recovery_pix_orders from service_role;
revoke all on table public.recovery_pix_jobs from service_role;

grant select on table public.recovery_pix_orders to service_role;
grant select on table public.recovery_pix_jobs to service_role;

revoke execute on function public.recovery_pix_acquire(text, text, text, integer) from public, anon, authenticated;
revoke execute on function public.recovery_pix_transition(text, text, text, text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_cancel(text, text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_reopen_cancel(text, text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_confirm_cancel(text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_job_enqueue(text, text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_job_acquire(text, text, text, integer) from public, anon, authenticated;
revoke execute on function public.recovery_pix_job_complete(text, text, text) from public, anon, authenticated;
revoke execute on function public.recovery_pix_job_fail(text, text, text, boolean) from public, anon, authenticated;

grant execute on function public.recovery_pix_acquire(text, text, text, integer) to service_role;
grant execute on function public.recovery_pix_transition(text, text, text, text) to service_role;
grant execute on function public.recovery_pix_cancel(text, text) to service_role;
grant execute on function public.recovery_pix_reopen_cancel(text, text) to service_role;
grant execute on function public.recovery_pix_confirm_cancel(text) to service_role;
grant execute on function public.recovery_pix_job_enqueue(text, text) to service_role;
grant execute on function public.recovery_pix_job_acquire(text, text, text, integer) to service_role;
grant execute on function public.recovery_pix_job_complete(text, text, text) to service_role;
grant execute on function public.recovery_pix_job_fail(text, text, text, boolean) to service_role;
