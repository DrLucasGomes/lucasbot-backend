# Kiwify — Documentação Técnica dos Webhooks de Checkout

**Registro inicial:** 28/08/2026  
**Atualização de validação:** 29/08/2026  
**Status:** VALIDADO EM PRODUÇÃO para os quatro eventos utilizados pelo LucasBot V3

## Resumo executivo

A Kiwify envia webhooks em JSON, permite selecionar eventos por produto e oferece teste/logs com reenvio. Como o suporte não definiu com precisão os critérios internos de abandono, a implementação foi consolidada com base em testes controlados e validações reais de produção.

Webhook oficial de produção:

`https://lucasbot-backend.onrender.com/kiwify`

Produto: **Protocolo Vigor 360**

Eventos ativos e confirmados:

- Boleto gerado
- Pix gerado
- Carrinho abandonado
- Compra aprovada

## Estados usados pelo backend

| Situação observada | Estado/rota | Ação |
|---|---|---|
| Checkout abandonado | `abandoned` | Recuperação de abandono |
| PIX gerado e pendente | `pix_pending` / `waiting_payment` | Recuperação específica de PIX |
| Boleto gerado e pendente | `boleto_pending` / `waiting_payment` | Recuperação específica de boleto |
| Pagamento aprovado | `paid` | Marcar comprador e interromper recuperações |

## Validações realizadas

### Carrinho abandonado

Confirmado em produção:

- evento recebido pelo backend;
- `status_pagamento = abandoned` persistido;
- tag `Abandono Vigor 360` aplicada no Kit;
- sequência de recuperação iniciada;
- após `paid`, tag removida e sequência retirada/interrompida.

### PIX

Confirmado em produção:

- `pix_created` inicia recuperação específica;
- estado persistido no Supabase;
- `paid` cancela a recuperação;
- jobs pendentes podem ser reconciliados pelo cron de produção.

### Boleto

Confirmado com boleto real compensado.

Pedido de validação:

- `order_id`: `210d922d-c45d-4869-b2e0-6ed315da6c81`
- `order_ref`: `K0KDXTN`
- método: boleto

Fluxo observado:

1. `billet_created` com `waiting_payment`;
2. tag de boleto pendente aplicada no Kit;
3. sequência de recuperação iniciada e e-mails enviados;
4. compensação real do boleto;
5. Kiwify enviou `order_approved` com `paid`;
6. Supabase permaneceu em `paid`;
7. `Comprador Vigor 360` presente no Kit;
8. tag de boleto pendente removida;
9. automação de boleto marcada como `Completed`;
10. sequência `Recuperação Boleto – Vigor 360` marcada como `Removed`.

### Compra aprovada

O evento `order_approved` é o estado terminal positivo para o fluxo atual. A regra operacional é:

**`paid` = comprador + nenhuma recuperação de pagamento incompatível ativa.**

## Reconciliação

O Cron Job Render `lucasbot-pix-reconcile` chama periodicamente:

`POST /internal/recovery-pix/reconcile`

Embora o nome seja histórico, o reconciliador cobre jobs de PIX e boleto e faz parte da produção.

## Decisão final

Para o escopo atual do LucasBot V3:

- abandono, PIX e boleto permanecem fluxos distintos;
- compra aprovada encerra recuperações incompatíveis;
- o webhook de produção é único;
- webhooks e serviços de teste antigos foram removidos;
- novas alterações transacionais exigem branch isolada, testes, PR e CI verde.

A evidência completa da validação final está registrada em `docs/LUCASBOT_V3_PRODUCTION_VALIDATION_2026-08-29.md`.
