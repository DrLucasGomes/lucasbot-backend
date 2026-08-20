# ADR-005: Recuperação de PIX por order_id e estado terminal de pagamento

- Status: proposto / em validação na branch `feat/pix-recovery`
- Data: 2026-08-20

## Contexto

A Kiwify possui um evento específico de PIX gerado. O contrato foi observado em um webhook real do Protocolo Vigor 360:

- `webhook_event_type = pix_created`;
- `order_status = waiting_payment`;
- `payment_method = pix`;
- `order_id` UUID estável da ordem.

`waiting_payment` isoladamente não é suficiente para classificar PIX, porque outros métodos de pagamento podem compartilhar estados pendentes.

A primeira implementação em branch usava `order_id` como chave primária, mas uma auditoria adversarial no VS Code/Codex encontrou uma falha crítica: se `paid` chegasse antes de `pix_created`, o pagamento não deixava tombstone no ledger e um PIX atrasado podia iniciar recuperação de comprador. A primeira correção adicionou tombstone e CAS, mas a segunda auditoria ainda encontrou dois riscos altos: timeout ambíguo durante `subscribe` sem compensação e falha de `unsubscribe` sem estado durável de retry. Também apontou permissões excessivas nas RPCs `SECURITY DEFINER` e ausência de caminho de upgrade caso uma 005 anterior tivesse sido aplicada.

## Decisão

A recuperação PIX é um efeito adicional do webhook Kiwify e não substitui a rota original. O wrapper executa primeiro o `/kiwify` existente e apenas depois tenta classificar/agendar PIX. Falhas dessa camada nunca devem alterar a resposta principal.

A tabela `recovery_pix_orders` usa `order_id` como chave primária e estados:

- `processing`;
- `subscribing`;
- `completed`;
- `failed`;
- `cancelled_pending_unsubscribe`;
- `cancelled`.

`completed`, `cancelled_pending_unsubscribe` e `cancelled` são terminais para aquisição de subscribe. `failed` pode ser retomado. `processing` e `subscribing` podem ser readquiridos quando stale por mais de 5 minutos.

As transições críticas são executadas por RPCs PostgreSQL atômicas:

1. `recovery_pix_acquire` cria ordem nova ou readquire `failed/stale`, mas nunca estados de cancelamento ou `completed`;
2. `recovery_pix_transition` permite somente `processing -> subscribing`, `subscribing -> completed` e `subscribing -> failed`;
3. `recovery_pix_cancel` cria/atualiza `cancelled_pending_unsubscribe`, inclusive quando pagamento chega antes do PIX;
4. `recovery_pix_confirm_cancel` muda pending para `cancelled` somente depois de unsubscribe remoto confirmado.

Pagamento persiste `cancelled_pending_unsubscribe` antes de qualquer chamada externa. Isso bloqueia imediatamente qualquer reativação da mesma `order_id`, mas mantém explícito que o efeito externo ainda pode precisar de retry.

Se o `unsubscribe` falhar ou sofrer timeout, o ledger permanece `cancelled_pending_unsubscribe`. Entregas futuras de `paid` ou `pix_created` podem tentar reconciliação novamente sem readquirir subscribe. `cancelled` significa que o Kit confirmou a remoção.

Antes de chamar o Kit para subscribe, o worker precisa vencer `processing -> subscribing`. Depois do subscribe, somente `subscribing -> completed` confirma sucesso. Se essa transição falhar porque pagamento concorrente já colocou a ordem em cancelamento, o worker executa reconciliação de unsubscribe. Se o próprio subscribe lançar timeout/exceção com resultado remoto ambíguo, o worker verifica primeiro se existe cancelamento e, nesse caso, tenta unsubscribe compensatório antes de qualquer retry de recovery.

## Segurança das RPCs

As funções `SECURITY DEFINER` fixam `search_path = pg_catalog, public`, usam objetos persistentes qualificados, revogam `EXECUTE` de `PUBLIC`, `anon` e `authenticated` e concedem execução somente a `service_role`.

## Garantia de entrega

A garantia entre Supabase e Kit é **at-least-once**, não exactly-once. Timeout ambíguo pode ocorrer depois de o Kit aceitar uma alteração e antes de o cliente receber a resposta. O ledger e a reconciliação protegem o comprador e tornam falhas de unsubscribe duráveis, mas não transformam duas APIs independentes em uma transação distribuída.

## Dados

O ledger PIX não deve persistir CPF, IP, `pix_code`, QR Code ou outros dados de pagamento. O mínimo operacional é `order_id`, e-mail e estado/timestamps.

## Migrations

`005_create_recovery_pix_orders.sql` representa a instalação limpa do contrato atual. `006_upgrade_recovery_pix_orders.sql` existe como upgrade idempotente para qualquer ambiente no qual uma versão anterior da 005 tenha sido aplicada; ele adiciona/ajusta colunas e constraint, remove `order_ref`, recria RPCs e reaplica permissões.

## Consequências

- `paid` anterior ou concorrente não pode reativar recuperação PIX;
- falha de unsubscribe permanece visível e reconciliável em estado pending;
- duplicatas normais da mesma `order_id` não iniciam nova recuperação;
- estados presos podem ser retomados após lease stale;
- a integração continua at-least-once e exige teste real de concorrência/transições no Supabase;
- a tag PIX deve ser própria (`TAG_PIX_ID`) e separada de abandono;
- antes do merge são obrigatórios nova auditoria Codex, suíte completa, migrations reais, teste de privilégios/RPCs, e E2E Kiwify -> Render -> Supabase -> Kit.
