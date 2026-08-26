# ADR-007: atribuição temporal mínima da recuperação PIX

- Status: aceito

## Contexto

O status operacional da recuperação é alterado quando ocorre o pagamento e os
timestamps genéricos do ledger representam mutações técnicas. Por isso, eles não
preservam quando a recuperação foi efetivamente concluída nem quando o pagamento
foi oficialmente confirmado.

## Decisão

Adicionar ao ledger `recovery_pix_orders` dois timestamps nullable e write-once:

- `recovery_completed_at`, preenchido atomicamente somente pela transição fenced
  `subscribing -> completed`;
- `paid_confirmed_at`, preenchido pela RPC durable de cancelamento, chamada somente
  depois que a API da Kiwify confirma o status `paid` da ordem.

As RPCs usam `coalesce(timestamp, now())`, preservando o primeiro horário em
retries e concorrência. Uma proteção write-once impede remoção ou sobrescrita.
Uma view deriva conversão e tempo até pagamento sem chamada HTTP, outbox ou
reconciler analítico adicional.

## Semântica

`recovery_conversion` significa somente que o pedido entrou na recuperação e
posteriormente foi pago. Não significa que a recuperação ou seus emails
causaram a compra.

Esta etapa não registra envio, abertura, clique, mensagem, last touch, janela de
atribuição ou UTM adicional.

Não há backfill com `created_at` ou `updated_at`: a atribuição confiável começa
quando a migration 009 for aplicada. Pedidos anteriores podem permanecer com os
dois timestamps nulos.

## Validação em produção

A migration 009 foi aplicada em produção e validada com um E2E real na ordem
`bce89324-3dff-4bcb-89e4-10b035a9867b`.

Antes do pagamento, a view apresentou `recovery_completed_at` preenchido em
`2026-08-26 17:51:57.444436+00`, `paid_confirmed_at` nulo,
`recovery_conversion=false` e delay nulo. Depois do pagamento da mesma ordem,
`recovery_completed_at` permaneceu inalterado, `paid_confirmed_at` foi preenchido
em `2026-08-26 17:56:34.323816+00`, `recovery_conversion=true` e
`conversion_delay_seconds=276.879380`.

O E2E confirmou a progressão temporal recovery -> paid e o comportamento
write-once de `recovery_completed_at`.

## Touch-level de emails

Atribuição por `email_1`, `email_2` ou `email_3` não foi implementada. Essa
extensão fica adiada até existir necessidade analítica comprovada e uma fonte
confiável de eventos do Kit que diferencie envio real, programação e clique.
