# ADR-009 — Exclusividade entre trilhas de recuperação

**Status:** aceito

## Contexto

O LucasBot possui quatro trilhas de comunicação no Kit que podem ser acionadas em momentos diferentes da mesma jornada: recuperação pós-VSL, abandono de checkout, PIX pendente e boleto pendente. O teste E2E de boleto e a revisão posterior mostraram que a recuperação pós-VSL não era automaticamente removida quando o lead avançava para PIX ou boleto, permitindo sobreposição de sequências.

## Decisão

`POST /kiwify` passa por um wrapper de convergência depois do processamento principal existente. O estado recebido da Kiwify determina quais tags de recuperação são incompatíveis e devem ser removidas do Kit:

- `abandoned`: remove recuperação pós-VSL;
- `pix_created` + `waiting_payment` + `payment_method=pix`: remove pós-VSL, abandono e boleto;
- `billet_created` + `waiting_payment` + `payment_method=boleto`: remove pós-VSL, abandono e PIX;
- `paid`: remove pós-VSL, abandono, PIX e boleto.

A tag/automação correspondente ao estado atual é mantida pelo fluxo que já existia. `paid` continua sendo estado terminal e mantém a tag de comprador.

## Entrega e retry

O handler Kiwify existente é executado exatamente uma vez por chamada do wrapper. Depois disso, a convergência de tags é tentada de forma síncrona. Se uma remoção configurada falhar, o endpoint devolve HTTP 503 para permitir reentrega pela Kiwify. As rotinas de PIX e boleto preservam adicionalmente a inbox durável e o reconciliador periódico já existentes.

## Consequência

O Kit deixa de poder manter, por desenho, a recuperação pós-VSL simultaneamente com uma recuperação de pagamento. Quando a compra é aprovada, nenhuma das quatro trilhas de recuperação deve permanecer ativa.
