# LucasBot V3 — Validação final de produção

**Data:** 29/08/2026  
**Status:** VALIDADO EM PRODUÇÃO

## Escopo validado

O LucasBot V3 foi validado ponta a ponta para os fluxos transacionais atualmente em produção, integrando Kiwify, backend FastAPI no Render, Supabase, Kit e ManyChat quando há correspondência de contato.

### Webhook oficial da Kiwify

Webhook único de produção:

`https://lucasbot-backend.onrender.com/kiwify`

Produto: **Protocolo Vigor 360**

Eventos ativos e confirmados em produção:

- `Boleto gerado`
- `Pix gerado`
- `Carrinho abandonado`
- `Compra aprovada`

Os webhooks de teste/staging foram removidos após a validação.

## Compra aprovada

O evento `order_approved` atualiza o lead no Supabase para `status_pagamento = paid`, aplica a tag `Comprador Vigor 360` no Kit e interrompe recuperações incompatíveis com o estado de comprador.

A ausência de contato correspondente no ManyChat não impede a persistência da compra no Supabase nem a atualização do Kit quando há e-mail válido.

## Carrinho abandonado

O evento de carrinho abandonado foi validado em produção:

- o backend recebe e persiste `status_pagamento = abandoned`;
- a tag `Abandono Vigor 360` é aplicada no Kit;
- o contato entra na sequência de recuperação;
- após `paid`, a tag de abandono é removida e a sequência de recuperação é retirada/interrompida.

## PIX

O fluxo de PIX foi validado com estado persistente e reconciliação:

- `pix_created` cria/atualiza o estado de recuperação;
- o contato entra na recuperação específica de PIX;
- `paid` cancela a recuperação correspondente;
- o cron de reconciliação garante novas tentativas de jobs pendentes/retryable/processing.

## Boleto — validação E2E real

A validação final foi realizada com compensação real de boleto, não apenas com payload simulado.

Pedido usado no teste:

- `order_id`: `210d922d-c45d-4869-b2e0-6ed315da6c81`
- `order_ref`: `K0KDXTN`
- método: `boleto`
- e-mail de teste: `testeboleto4@drlucasgomes.com.br`

### Estado inicial

O evento `billet_created` chegou com `order_status = waiting_payment`.

Resultado confirmado:

- Supabase em `waiting_payment`;
- tag de boleto pendente aplicada no Kit;
- sequência `Recuperação Boleto – Vigor 360` iniciada;
- e-mails de recuperação efetivamente enviados.

### Compensação

Após a compensação real, a Kiwify enviou:

- `webhook_event_type = order_approved`
- `order_status = paid`
- `payment_method = boleto`

Resultado final confirmado:

- Supabase: `status_pagamento = paid`;
- Kit: tag `Comprador Vigor 360` presente;
- Kit: tag de boleto pendente removida;
- automação `Boleto Pendente → Recuperação – Vigor 360`: `Completed`;
- sequência `Recuperação Boleto – Vigor 360`: `Removed`.

Conclusão: um comprador que paga boleto não permanece recebendo comunicação de cobrança.

## Correção encontrada durante o teste final

O E2E revelou que a implementação completa de recuperação de boleto ainda existia em uma branch antiga divergente (`feat/boleto-recovery`) e não estava integralmente na `main`.

A correção foi portada de forma seletiva para uma branch nova baseada na `main` atual, evitando merge bruto da branch divergente.

PR: **#16 — Port boleto recovery onto current main**  
Merge commit: `a9da78798a7a18fc19c860715b1e70a049b1c26b`

O CI passou antes do merge.

## Reconciliação de pagamentos

O recurso Render `lucasbot-pix-reconcile` é um **Cron Job de produção** e deve ser preservado.

Ele chama periodicamente:

`POST https://lucasbot-backend.onrender.com/internal/recovery-pix/reconcile`

com autenticação por `PIX_RECOVERY_WORKER_TOKEN`.

Apesar do nome histórico conter `pix`, o reconciliador atualmente também cobre os jobs de recuperação de boleto. Não é serviço de teste.

## Infra Render após limpeza

Serviços de produção dentro do projeto:

- `lucasbot-backend`
- `formulario-consultorio`

Cron de produção separado:

- `lucasbot-pix-reconcile`

Serviços de teste antigos removidos:

- `lucasbot-backend-staging`
- `lucasbot-first-name-test`
- `lucasbot-tracking-test`

## Estado operacional final

Para o escopo atual, o LucasBot V3 fica considerado operacionalmente validado em produção para:

- captura/persistência de leads;
- tracking de origem disponível no checkout;
- compra aprovada;
- abandono de checkout;
- PIX pendente e cancelamento após pagamento;
- boleto pendente e cancelamento após pagamento;
- integração com Kit;
- atualização de comprador no Supabase;
- reconciliação de jobs de recuperação.

## Regra de congelamento

A partir deste checkpoint, mudanças no caminho transacional devem ser tratadas como nova alteração de produção: branch isolada, testes automatizados, PR, CI verde e validação controlada antes de merge.

O objetivo deste documento é servir como ponto de retomada para evitar reconstrução de contexto em futuras alterações do LucasBot.
