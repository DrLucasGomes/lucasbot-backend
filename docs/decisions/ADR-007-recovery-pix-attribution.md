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
