# ADR-004: Recuperação após o primeiro play da VSL

- Status: aceito e validado em produção

## Contexto

O Protocolo Vigor 360 inicia uma recuperação comercial quando um lead identificado começa a assistir à VSL. Esse evento é diferente do clique no checkout e do abandono de checkout (`cart_abandoned`): o gatilho operacional desta recuperação é somente o primeiro **PLAY** elegível da VSL do Vigor 360.

## Decisão

O backend expõe `POST /recovery/video-play`. Na V1, a identidade é aceita exclusivamente no formato `src=mc_<manychat_id>`. O navegador nunca fornece um e-mail confiável: o endpoint localiza o contato por `manychat_id` e obtém o e-mail exclusivamente de `leads_vigor`.

Leads inexistentes, sem e-mail válido ou com `status_pagamento` em `STATUS_PAGOS` são inelegíveis. Para leads elegíveis, o backend aplica no Kit a tag `recuperacao-pos-clique-vigor360`.

O WordPress/VSL usa a YouTube IFrame API (`enablejsapi=1`) para detectar o estado real `PLAYING`. O JavaScript lê `src` da URL e só chama o endpoint quando o valor corresponde a `mc_<número>`. A falha de tracking é silenciosa e nunca pode impedir o vídeo de tocar.

O CORS do endpoint aceita a VSL nos hosts `https://drlucasgomes.com.br` e `https://www.drlucasgomes.com.br`, limitado ao necessário para o POST de tracking.

## Sequência no Kit

A tag `recuperacao-pos-clique-vigor360` inscreve o contato na automação/sequência `Vigor 360 — Recuperação Pós-Clique`.

Cadência definitiva:

1. primeiro PLAY elegível;
2. espera de 1 hora;
3. E-mail 1;
4. espera de 1 dia;
5. E-mail 2;
6. espera de 2 dias;
7. E-mail 3.

O fluxo de compra permanece separado. Uma compra `paid` deve aplicar `Comprador Vigor 360` e retirar o contato da recuperação antes do próximo e-mail. A validação E2E dessa interrupção após o E-mail 1 ainda está pendente.

## Atribuição das vendas recuperadas

Os CTAs `CONHECER O VIGOR 360` usam:

- `utm_source=kit`
- `utm_medium=email`
- `utm_campaign=recovery_vigor360`
- `utm_content=email_1`, `email_2` ou `email_3`

A VSL preserva esses parâmetros ao abrir o checkout da Kiwify. O webhook `/kiwify` extrai e persiste a atribuição em `checkout_utm_source`, `checkout_utm_medium`, `checkout_utm_campaign` e `checkout_utm_content`.

Isso permite medir vendas recuperadas por e-mail específico. O teste sintético do E-mail 1 confirmou `email_1 -> VSL -> Kiwify -> /kiwify -> Supabase`, com `checkout_utm_content=email_1`.

`src` não é usado para identificar o número do e-mail; ele permanece reservado à identidade/origem quando aplicável. `utm_content` identifica o e-mail que gerou o clique.

## Idempotência e estado operacional

A tabela `recovery_video_plays` registra uma linha única por `manychat_id` e usa os estados:

- `processing`: uma tentativa está em andamento;
- `completed`: a tag foi aplicada com resposta de sucesso e o estado é terminal;
- `failed`: a tentativa falhou e pode ser retomada posteriormente.

Um `processing` recente bloqueia concorrência e reentrada. Um `processing` cujo `updated_at` tenha mais de 5 minutos é considerado stale e pode ser readquirido atomicamente.

Não existe garantia de exactly-once distribuída entre Supabase e Kit. A V1 adota entrega at-least-once com deduplicação local e aproveita a natureza idempotente da associação da mesma tag no Kit.

A unicidade atual é por `manychat_id`; portanto, cada lead entra nessa recuperação uma única vez na V1 depois que alcança `completed`.

## Evidências de validação em produção

Foram confirmados:

- primeiro PLAY real criando `recovery_video_plays` e chegando a `completed`;
- pausa/PLAY repetido sem duplicar registro;
- acesso sem `src=mc_...` sem disparar recuperação;
- aplicação da tag `recuperacao-pos-clique-vigor360` no Kit;
- inscrição automática do lead na sequência `Vigor 360 — Recuperação Pós-Clique`;
- preservação de `utm_source=kit`, `utm_medium=email`, `utm_campaign=recovery_vigor360` e `utm_content=email_1` da VSL até a Kiwify;
- persistência de `checkout_utm_content=email_1` pelo webhook `/kiwify`.

Teste E2E em andamento: lead inscrito com sucesso na sequência real, aguardando o disparo do E-mail 1 para então simular `paid` e confirmar que E-mails 2 e 3 não são enviados.

## Limites e consequências

- A falha da recuperação nunca pode impedir o vídeo de tocar.
- Não há worker, scheduler, fila ou envio direto de e-mails pelo backend; a cadência pertence ao Kit.
- `journey_events` não é usado como mecanismo operacional desta recuperação.
- Recuperação pós-play e `cart_abandoned` permanecem fluxos distintos.
- Token assinado e `journey_run_id` na URL da VSL ficam como hardening futuro.
