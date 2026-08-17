# ADR-001: `journey_events` append-only

- Status: aceito

## Contexto

O estado consolidado em `leads_vigor` não permite reconstruir com segurança a sequência de acontecimentos de uma passagem pelo funil. Também é necessário tolerar reenvios sem criar eventos duplicados.

## Decisão

`journey_events` é um log append-only. Cada acontecimento é inserido como uma nova linha. A migration instala um trigger `BEFORE UPDATE OR DELETE` que usa `prevent_update_delete_journey_events` para impedir alterações e exclusões.

`dedupe_key` permanece `UNIQUE` global. Ela representa a identidade do evento e sua unicidade não depende de `manychat_id` nem de `journey_run_id`. Uma tentativa repetida que produza `23505` é aceita pela API como idempotente.

## Consequências

- O histórico mantém ordem e evidência dos eventos recebidos.
- Correções são registradas como novos eventos; linhas antigas não são reescritas.
- A geração da `dedupe_key` deve evitar reutilização acidental, inclusive entre runs.
- A garantia definitiva de append-only reside no banco; a aplicação apenas realiza inserts na coleção.
