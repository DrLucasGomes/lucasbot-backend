# ADR-008: recuperacao durable de boleto - fase 1

- Status: proposto para validacao

## Contexto

O webhook real da Kiwify comprovou o contrato de boleto gerado:

- `webhook_event_type=billet_created`;
- `payment_method=boleto`;
- `order_status=waiting_payment`;
- `boleto_expiry_date` no formato `DD/MM/YYYY`.

O payload tambem contem URL e codigo de barras, mas esses dados nao sao
necessarios para coordenar a recuperacao e nao devem ser persistidos.

## Decisao

Ampliar de forma compativel a inbox e o ledger durable existentes, sem renomear
tabelas produtivas e sem duplicar a arquitetura PIX. O boleto usa o mesmo CAS,
fencing, stale recovery, retry e atribuicao write-once, mas possui tag Kit
exclusiva em `TAG_BOLETO_ID`.

O subscribe da tag boleto envia `api_secret`, `email` e `first_name` valido na
mesma operacao. No pagamento confirmado server-to-server, o metodo retornado
pela Kiwify seleciona exclusivamente a tag a remover: boleto nao remove PIX e
PIX nao remove boleto.

`expires_at` e armazenado apenas como dado tecnico, sem backfill. A data sem hora
observada no webhook e normalizada deterministicamente para meia-noite UTC e nao
e usada como instante de cancelamento.

## Fora da fase 1

Nao existe job, timer, sleep nem remocao de tag baseada no relogio. Antes de
automatizar retirada da recuperacao, e obrigatorio confirmar o contrato Kiwify
de boleto expirado e o comportamento de pagamentos proximos ou posteriores ao
vencimento.
