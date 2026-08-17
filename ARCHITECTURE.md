# Arquitetura

## Estado do lead e histórico da jornada

`leads_vigor` mantém o estado consolidado e atual do lead. Seus registros podem ser atualizados conforme novas informações chegam e são usados pelos fluxos operacionais existentes.

`journey_events` mantém o histórico de acontecimentos do funil. Cada acontecimento gera uma nova linha; registros existentes não são atualizados nem removidos. A tabela é, portanto, append-only.

## Identificadores

- `manychat_id` identifica o contato no ManyChat e liga suas diferentes passagens pelo funil.
- `journey_run_id` identifica uma passagem completa desse contato pelo funil. Um mesmo `manychat_id` pode ter vários runs.
- `dedupe_key` identifica unicamente um evento para tornar reenvios idempotentes. Sua unicidade é global e independe do `journey_run_id`.

O mesmo `journey_run_id` deve acompanhar os eventos de `idade`, `tempo_sintoma`, `fator_risco`, `status_testosterona`, `email` e `parte_final` durante uma passagem completa.

## Endpoints de jornada

`POST /journey/run` apenas gera e devolve um UUID v4. Ele não cria lead, não persiste run e não acessa serviços externos.

`POST /journey/event` valida o contrato e tenta inserir um evento no Supabase. Essa gravação é best-effort: indisponibilidade, timeout ou rejeição da persistência são reportados no corpo da resposta, sem quebrar o fluxo principal do funil. Uma violação de unicidade PostgreSQL `23505` é tratada como reenvio idempotente.

Eventos históricos sem `journey_run_id` são aceitos por compatibilidade. Eles representam o período de transição e não devem ser incluídos em análises da jornada nova baseadas em runs completos.

## Limites de mudança

A instrumentação de jornada é adicional. Ela não altera os contratos de `/webhook`, `/kiwify`, tracking, `leads_vigor` ou `click_sessions`.
