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

A primeira implementação em branch usava `order_id` como chave primária, mas uma auditoria adversarial no VS Code/Codex encontrou uma falha crítica: se `paid` chegasse antes de `pix_created`, o pagamento não deixava tombstone no ledger e um PIX atrasado podia iniciar recuperação de comprador. A auditoria também encontrou corrida entre `paid` e `pix_created`, ausência de recuperação de `processing` stale e alteração do comportamento de JSON inválido no wrapper.

## Decisão

A recuperação PIX é um efeito adicional do webhook Kiwify e não substitui a rota original. O wrapper executa primeiro o `/kiwify` existente e apenas depois tenta classificar/agendar PIX. Falhas dessa camada nunca devem alterar a resposta principal.

A tabela `recovery_pix_orders` usa `order_id` como chave primária e estados:

- `processing`;
- `subscribing`;
- `completed`;
- `failed`;
- `cancelled`.

`cancelled` e `completed` são terminais para aquisição. `failed` pode ser retomado. `processing` e `subscribing` podem ser readquiridos quando stale por mais de 5 minutos.

As transições críticas são executadas por RPCs PostgreSQL atômicas:

1. `recovery_pix_acquire` cria uma ordem nova ou readquire `failed/stale`, mas nunca `cancelled/completed`;
2. `recovery_pix_transition` executa compare-and-set entre estados de trabalho;
3. `recovery_pix_cancel` cria ou atualiza uma tombstone `cancelled`, inclusive quando o pagamento chega antes do evento PIX.

Antes de chamar o Kit, o worker precisa vencer `processing -> subscribing`. Depois de `subscribe`, somente `subscribing -> completed` confirma sucesso. Se essa transição falhar porque um pagamento concorrente já gravou `cancelled`, o worker executa `unsubscribe` compensatório.

Pagamento persiste `cancelled` antes da chamada externa ao Kit. Um `unsubscribe` que falhar não permite reativar a ordem, embora ainda possa exigir retry/reconciliação externa.

## Garantia de entrega

A garantia entre Supabase e Kit é **at-least-once**, não exactly-once. Um timeout ambíguo pode ocorrer depois de o Kit aceitar uma alteração e antes de o cliente receber a resposta. A chave/estado local reduz duplicidade e protege compradores, mas não transforma duas APIs independentes em uma transação distribuída.

## Dados

O ledger PIX não deve persistir CPF, IP, `pix_code`, QR Code ou outros dados de pagamento. O mínimo operacional é `order_id`, e-mail e estado/timestamps.

## Consequências

- `paid` anterior ou concorrente não pode reativar recuperação PIX;
- duplicatas normais da mesma `order_id` não iniciam nova recuperação;
- estados presos podem ser retomados após lease stale;
- a migration `005_create_recovery_pix_orders.sql` passa a ser requisito de deploy;
- a tag PIX deve ser própria (`TAG_PIX_ID`) e separada de abandono;
- antes do merge é obrigatório repetir auditoria Codex, suíte completa, teste integrado de concorrência/transições no Supabase e teste E2E real Kiwify -> Render -> Supabase -> Kit.
