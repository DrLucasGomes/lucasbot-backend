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

As auditorias adversariais no VS Code/Codex encontraram sucessivamente problemas que não apareciam na suíte nominal: `paid` antes de `pix_created`, corrida entre pagamento e subscribe, `processing` preso, timeout ambíguo, unsubscribe sem retry durável e, na terceira rodada, um subscribe remoto tardio capaz de ocorrer depois de um unsubscribe já confirmado. A terceira auditoria também apontou risco ABA quando um worker stale pudesse voltar depois de uma nova tentativa.

## Decisão

A recuperação PIX é um efeito adicional do webhook Kiwify e não substitui a rota original. O wrapper executa primeiro o `/kiwify` existente e apenas depois tenta classificar/agendar PIX. Falhas dessa camada nunca devem alterar a resposta principal.

A tabela `recovery_pix_orders` usa `order_id` como chave primária e estados:

- `processing`;
- `subscribing`;
- `completed`;
- `failed`;
- `cancelled_pending_unsubscribe`;
- `cancelled`.

Cada aquisição gera um `attempt_token` único. Esse token funciona como fencing token: todas as transições de trabalho exigem o token atual. Quando uma tentativa `failed` ou stale é readquirida, o banco substitui o token; um worker antigo deixa de ter autoridade para concluir, falhar ou reabrir o cancelamento da nova tentativa.

`completed`, `cancelled_pending_unsubscribe` e `cancelled` não são elegíveis para nova aquisição de subscribe. `failed` pode ser retomado. `processing` e `subscribing` podem ser readquiridos quando stale por mais de 5 minutos.

As transições críticas são executadas por RPCs PostgreSQL atômicas:

1. `recovery_pix_acquire` cria ordem nova ou readquire `failed/stale`, gravando um novo `attempt_token`;
2. `recovery_pix_transition` permite somente `processing -> subscribing`, `subscribing -> completed` e `subscribing -> failed`, exigindo `attempt_token` correspondente;
3. `recovery_pix_cancel` cria/atualiza `cancelled_pending_unsubscribe`, inclusive quando pagamento chega antes do PIX, preservando o token de eventual tentativa em voo;
4. `recovery_pix_reopen_cancel` permite ao worker que efetivamente tentou subscribe reabrir `cancelled -> cancelled_pending_unsubscribe` somente se ainda possui o fencing token daquela tentativa;
5. `recovery_pix_confirm_cancel` muda pending para `cancelled` somente depois de unsubscribe remoto confirmado.

Pagamento persiste `cancelled_pending_unsubscribe` antes de qualquer chamada externa. Isso bloqueia imediatamente qualquer reativação da mesma `order_id`, mas mantém explícito que o efeito externo ainda pode precisar de retry.

Se um subscribe confirmado retornar depois de um pagamento já ter executado unsubscribe e marcado `cancelled`, o worker perde o CAS para `completed`, reabre atomicamente o estado para `cancelled_pending_unsubscribe` com seu `attempt_token`, executa um novo unsubscribe depois desse subscribe conhecido e só então pode confirmar `cancelled`.

Se o subscribe terminar localmente em timeout/exceção, o resultado remoto é ambíguo. Mesmo que uma compensação de unsubscribe retorne sucesso, o fluxo não confirma `cancelled` nessa mesma passagem; mantém `cancelled_pending_unsubscribe` para que a divergência potencial permaneça detectável e possa ser reconciliada em entrega futura.

## Segurança das RPCs

As funções `SECURITY DEFINER` fixam `search_path = pg_catalog, public`, usam objetos persistentes qualificados, revogam `EXECUTE` de `PUBLIC`, `anon` e `authenticated` e concedem execução somente a `service_role`.

## Garantia de entrega

A garantia entre Supabase e Kit é **at-least-once**, não exactly-once. Fencing token resolve concorrência entre workers locais, mas não transforma a API do Kit em participante de uma transação PostgreSQL. Timeout remoto pode deixar resultado desconhecido; nesses casos o sistema prefere manter estado pendente detectável a declarar cancelamento terminal sem evidência suficiente.

## Dados

O ledger PIX não deve persistir CPF, IP, `pix_code`, QR Code ou outros dados de pagamento. O mínimo operacional é `order_id`, e-mail, `attempt_token` e estado/timestamps.

## Migrations

`005_create_recovery_pix_orders.sql` representa a instalação limpa do contrato atual. `006_upgrade_recovery_pix_orders.sql` existe como upgrade idempotente para qualquer ambiente no qual uma versão anterior da 005 tenha sido aplicada; ele adiciona `attempt_token`, ajusta colunas/constraint, remove assinaturas antigas das RPCs, cria as versões cercadas por fencing e reaplica permissões.

## Consequências

- `paid` anterior ou concorrente não pode reativar recuperação PIX;
- worker stale não pode modificar uma tentativa nova depois de readquisição;
- subscribe tardio conhecido após cancelamento força nova compensação antes de voltar a `cancelled`;
- timeout ambíguo nunca é escondido por um `cancelled` prematuro;
- falha de unsubscribe permanece visível e reconciliável em estado pending;
- duplicatas normais da mesma `order_id` não iniciam nova recuperação;
- a integração continua at-least-once e exige teste real de concorrência/transições no Supabase;
- a tag PIX deve ser própria (`TAG_PIX_ID`) e separada de abandono;
- antes do merge são obrigatórios nova auditoria Codex, suíte completa, migrations reais, teste de privilégios/RPCs, e E2E Kiwify -> Render -> Supabase -> Kit.
