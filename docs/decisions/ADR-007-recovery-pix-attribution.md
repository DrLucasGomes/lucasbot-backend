# ADR-007: atribuição temporal mínima da recuperação PIX

- Status: aceito

## Contexto

O ledger e os jobs da recuperação PIX preservam estado operacional, mas não um
histórico analítico estável da entrada efetiva na recuperação seguida de
pagamento.

## Decisão

Registrar eventos append-only e idempotentes por `order_id`:

- `recovery_entered`, depois que a aplicação da recuperação e a transição local
  para `completed` forem confirmadas;
- `purchase_completed`, depois que o mecanismo existente validar oficialmente
  o status `paid` da mesma ordem.

Uma view deriva timestamps, conversão e tempo até pagamento. Falhas analíticas
são fail-open e não participam das decisões operacionais do PIX.

## Semântica

`recovery_conversion` significa somente que o pedido entrou na recuperação e
posteriormente foi pago. Não significa que a recuperação ou seus emails
causaram a compra.

Esta etapa não registra envio, abertura, clique, mensagem, last touch, janela de
atribuição ou UTM adicional.
