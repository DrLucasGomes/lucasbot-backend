# ADR-010 — E-mail como identidade primária nos eventos Kiwify

**Status:** aceito

## Contexto

Durante o teste E2E de 30/08/2026, um novo lead (`testefinal@drlucasgomes.com.br`) reutilizou um telefone já presente em um registro antigo marcado como `paid`. A resolução anterior consultava `manychat_id` e telefone antes do e-mail. Como consequência, o webhook de abandono foi associado ao comprador antigo, preservou `paid` e impediu a entrada correta na recuperação de checkout.

O Kit identifica subscribers, tags e sequências pelo e-mail. Portanto, em eventos Kiwify que fornecem e-mail, usar telefone antes do e-mail cria risco de colisão entre pessoas diferentes, números reutilizados ou telefones compartilhados.

## Decisão

`buscar_lead_existente()` passa a resolver identidade nesta ordem:

1. e-mail, quando presente;
2. `manychat_id`, quando não houver correspondência por e-mail;
3. telefone, `telefone_whatsapp` e `telefone_checkout_kiwify` apenas como fallback.

Nenhuma lógica de PIX, boleto, tracking, comprador ou recuperação é reescrita por esta mudança.

## Consequência

Um novo e-mail não pode mais herdar `paid`, tracking ou estado de recuperação de outro registro apenas porque reutilizou o mesmo telefone. A identidade usada para sincronizar o Kit passa a ser coerente com a própria chave operacional do Kit.

## Validação

Foram adicionados testes de regressão cobrindo:

- e-mail existente versus telefone pertencente a outro comprador pago;
- fallback para `manychat_id` e telefone quando e-mail não está disponível.
