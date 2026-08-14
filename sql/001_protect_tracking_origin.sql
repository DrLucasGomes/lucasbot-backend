-- Protege a origem/campanha de aquisicao contra sobrescrita por fallback.
-- Regra estreita: somente impede downgrade para os valores de baixa prioridade
-- usados pelo fallback atual. Demais atualizacoes continuam normalmente.

create or replace function public.protect_tracking_origin()
returns trigger
language plpgsql
as $$
begin
  if old.origem is not null
     and btrim(old.origem) <> ''
     and lower(btrim(coalesce(new.origem, ''))) = 'whatsapp direto'
  then
    new.origem := old.origem;
  end if;

  if old.campanha is not null
     and btrim(old.campanha) <> ''
     and lower(btrim(coalesce(new.campanha, ''))) = 'fallback_entrada'
  then
    new.campanha := old.campanha;
  end if;

  return new;
end;
$$;

drop trigger if exists trg_protect_tracking_origin on public.leads_vigor;

create trigger trg_protect_tracking_origin
before update on public.leads_vigor
for each row
execute function public.protect_tracking_origin();
