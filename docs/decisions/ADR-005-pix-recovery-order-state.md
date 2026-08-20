# ADR-005: Recuperação de PIX por order_id, fencing token e cancelamento reconciliável

- Status: proposto / em validação na branch `feat/pix-recovery`
- Data: 2026-08-20

## Contexto

A Kiwify possui um evento específico de PIX gerado. O contrato foi observado em um webhook real do Protocolo Vigor 360:

- `webhook_event_type = pix_created`;
- `order_status = waiting_payment`;
- `payment_method = pix`;
- `order_id` UUID estável da ordem.

`waiting_payment` isoladamente não é suficiente para classificar PIX, porque outros métodos de pagamento podem compartilhar estados pendentes.

As auditorias adversariais no VS Code/Codex encontraram sucessivamente problemas que não apareciam na suíte nominal: `paid` antes de `pix_created`, corrida entre pagamento e subscribe, `processing` preso, timeout ambíguo, unsubscribe sem retry durável, subscribe tardio depois de unsubscribe confirmado e risco ABA após readquisição stale. A quarta auditoria mostrou ainda um limite do fencing: um efeito remoto de um token antigo pode ser efetivado depois que uma tentativa nova substituiu o token; nesse caso o worker antigo não pode reabrir o estado atual.

## Decisão

A recuperação PIX é um efeito adicional do webhook Kiwify e não substitui a rota original. O wrapper executa primeiro o `/kiwify` existente e apenas depois tenta classificar/agendar PIX. Falhas dessa camada nunca devem alterar a resposta principal.

A tabela `recovery_pix_orders` usa `order_id` como chave primária e estados:

- `processing`;
- `subscribing`;
- `completed`;
- `failed`;
- `cancelled_pending_unsubscribe`;
- `cancelled`.

Cada aquisição gera um `attempt_token` único. Esse token funciona como fencing token para as transições de trabalho. Além disso, `subscribe_attempted` é um marcador monotônico: passa para `true` quando qualquer tentativa vence `processing -> subscribing` e nunca volta para `false`.

O marcador monotônico existe para cobrir efeitos remotos tardios que o fencing local não consegue eliminar. Se `subscribe_attempted=true`, o sistema **não fecha automaticamente a ordem em `cancelled`**, mesmo depois de um unsubscribe bem-sucedido. A ordem permanece `cancelled_pending_unsubscribe`, detectável e elegível para reconciliações futuras. Assim não existe estado terminal local que esconda a possibilidade de um subscribe remoto antigo ser efetivado depois.

`cancelled` automático fica reservado a ordens que nunca chegaram a iniciar subscribe (`subscribe_attempted=false`), por exemplo pagamento que chegou antes de qualquer recovery PIX.

As transições críticas são executadas por RPCs PostgreSQL atômicas:

1. `recovery_pix_acquire` cria ordem nova ou readquire `failed/stale`, gravando novo `attempt_token` sem apagar `subscribe_attempted`;
2. `recovery_pix_transition` permite somente `processing -> subscribing`, `subscribing -> completed` e `subscribing -> failed`, exigindo token atual; a primeira transição marca `subscribe_attempted=true`;
3. `recovery_pix_cancel` cria/atualiza `cancelled_pending_unsubscribe`; se uma ordem antiga estiver `cancelled` mas tiver `subscribe_attempted=true`, volta para pending;
4. `recovery_pix_reopen_cancel` exige token atual e `subscribe_attempted=true`;
5. `recovery_pix_confirm_cancel` só permite pending -> `cancelled` quando `subscribe_attempted=false`.

Pagamento persiste `cancelled_pending_unsubscribe` antes de qualquer chamada externa. A reconciliação tenta `unsubscribe`. Se nunca houve subscribe, sucesso permite `cancelled`. Se houve qualquer tentativa de subscribe, sucesso remove a tag naquele instante, mas o ledger continua pending por segurança distribuída.

## Garantia de entrega e limite distribuído

A garantia entre Supabase e Kit é **at-least-once**, não exactly-once. Fencing token resolve autoridade de workers locais, mas não cancela efeitos já aceitos ou ainda em voo no servidor remoto. Por isso o sistema prefere um pending durável a um `cancelled` potencialmente falso.

A consequência operacional é intencional: algumas ordens pagas que chegaram a tentar subscribe podem permanecer `cancelled_pending_unsubscribe` indefinidamente até existir uma reconciliação posterior explícita/monitorada. Isso é mais seguro do que perder detectabilidade de divergência entre ledger e Kit.

## Segurança das RPCs

As funções `SECURITY DEFINER` fixam `search_path = pg_catalog, public`, usam objetos persistentes qualificados, revogam `EXECUTE` de `PUBLIC`, `anon` e `authenticated` e concedem execução somente a `service_role`.

## Dados

O ledger PIX não persiste CPF, IP, `pix_code`, QR Code ou payload completo. O mínimo operacional é `order_id`, e-mail, `attempt_token`, `subscribe_attempted`, estado e timestamps.

## Migrations

`005_create_recovery_pix_orders.sql` representa a instalação limpa. `006_upgrade_recovery_pix_orders.sql` é upgrade defensivo e semanticamente idempotente. O backfill conservador de `subscribe_attempted` roda somente quando a coluna está sendo introduzida; reaplicar a 006 em um schema já atualizado não reclassifica ordens novas. Na primeira execução sobre schema legado, a migration adiciona `attempt_token` e `subscribe_attempted`, marca conservadoramente estados antigos quando necessário, converte `cancelled` antigo suspeito para pending, ajusta schema/RPCs e reaplica permissões.

## Consequências

- `paid` anterior ou concorrente não reativa recuperação PIX;
- worker stale não altera tentativa nova;
- qualquer ordem que já tentou subscribe continua com risco remoto visível em pending após pagamento;
- efeito remoto tardio de token antigo não pode resultar em `ledger=cancelled` silencioso, porque `subscribe_attempted` é monotônico e independente do token atual;
- falha de unsubscribe permanece reconciliável;
- a tag PIX continua própria (`TAG_PIX_ID`) e separada de abandono;
- antes do merge são obrigatórios nova auditoria Codex, suíte completa, migrations reais, teste de privilégios/RPCs e E2E Kiwify -> Render -> Supabase -> Kit.
