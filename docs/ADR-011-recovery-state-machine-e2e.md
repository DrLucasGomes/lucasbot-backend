# ADR-011 — Máquina de estados de recuperação e validação E2E

Data: 2026-08-30
Status: aceito

## Contexto

O LucasBot possui múltiplas recuperações no Kit para o Protocolo Vigor 360: pós-clique na VSL, checkout abandonado, PIX pendente e boleto pendente. Essas automações não podem concorrer entre si e nenhuma recuperação pode continuar após pagamento aprovado.

Durante o E2E real foi observado que a Kiwify pode reenviar o carrinho abandonado como payload achatado, sem o envelope `cart`. Também foi validado que a identidade principal para eventos Kiwify deve ser o e-mail, porque é o identificador usado pelo Kit para subscribers, tags e sequências.

## Decisão

A rota `/kiwify` classifica o estado comercial em `abandoned`, `pix_pending`, `boleto_pending` ou `paid`, aceitando tanto payloads envelopados quanto achatados.

A convergência de tags do Kit segue estas regras:

- `abandoned`: aplica `Abandono Vigor 360` e remove `recuperacao-pos-clique-vigor360`.
- `pix_pending`: remove pós-clique, abandono e boleto pendente, mantendo somente a recuperação de PIX.
- `boleto_pending`: remove pós-clique, abandono e PIX pendente, mantendo somente a recuperação de boleto.
- `paid`: remove todas as tags de recuperação. `Comprador Vigor 360` é aplicado pela lógica principal de pagamento.

`paid` é estado terminal. Um comprador já pago não pode reentrar em abandono, PIX pendente ou boleto pendente.

A resolução de identidade para webhooks Kiwify prioriza e-mail. ManyChat ID e telefone são apenas mecanismos secundários/fallback.

## Configuração do Kit validada

A automação `Vigor 360 — Recuperação Pós-Clique` possui eventos de saída por tag:

- `Comprador Vigor 360` → fim da automação.
- `Abandono Vigor 360` → fim da automação.

A automação `Vigor 360 — Recuperação Checkout Abandonado` possui proteção de comprador e evento de saída por `Comprador Vigor 360`.

Assim, remover a tag de entrada no backend não é a única proteção: o próprio Kit encerra a sequência ativa quando recebe uma tag de estado mais avançado.

## E2E validado

Lead de teste: `testefinal2@drlucasgomes.com.br`.

Fluxo observado:

1. Lead entrou em `Vigor 360 — Recuperação Pós-Clique`.
2. Evento de abandono foi enviado ao `/kiwify`.
3. O backend localizou o mesmo lead no Supabase (`id=1880`) e preservou os dados de origem do lead.
4. `Abandono Vigor 360` foi aplicada.
5. `recuperacao-pos-clique-vigor360` foi removida.
6. No Kit, `Vigor 360 — Recuperação Pós-Clique` passou para `Completed/Removed`.
7. `Vigor 360 — Recuperação Checkout Abandonado` ficou `Active`.
8. Uma compra PIX real foi aprovada para o mesmo e-mail e telefone.
9. O webhook `paid` atualizou o mesmo registro Supabase (`id=1880`) para `status_pagamento=paid` e `produto=Protocolo Vigor 360`.
10. ManyChat retornou `success`.
11. No Kit, `Comprador Vigor 360` ficou presente e as sequências Pós-Clique e Checkout Abandonado passaram para `Removed`.
12. A compra preservou tracking de recuperação por e-mail (`utm_source=kit`, `utm_medium=email`, `utm_campaign=recovery_vigor360`, `utm_content=email_1`).

## Resultado

Fluxo validado de ponta a ponta:

`Lead → Pós-Clique → Checkout Abandonado → Compra → encerra todas as recuperações`.

O sistema não deve enviar simultaneamente recuperação Pós-Clique e Checkout Abandonado para o mesmo subscriber, e nenhuma recuperação deve permanecer ativa após `paid`.

## Observabilidade

Os logs detalhados temporários usados no diagnóstico foram removidos após a validação. Permanecem apenas logs de erro/configuração necessários para operação. O endpoint retorna `503` quando a convergência crítica com o Kit falha, permitindo reentrega em vez de sucesso silencioso.

## Pendência não bloqueante

`origem_compra` ainda pode aparecer como `rastreado_outro` para compras atribuídas a `kit/email/recovery_vigor360`. Futuramente pode ser criado um mapeamento semântico específico, por exemplo `recuperacao_email`, apenas para melhorar relatórios. Isso não afeta o funcionamento do funil.
