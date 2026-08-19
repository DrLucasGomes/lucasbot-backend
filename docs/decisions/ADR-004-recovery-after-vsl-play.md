# ADR-004: Recuperação após o primeiro play da VSL

- Status: aceito

## Contexto

O Protocolo Vigor 360 precisa iniciar uma recuperação comercial quando um lead
identificado começa a assistir à VSL. Esse evento é diferente do clique no
checkout e do abandono de checkout (`cart_abandoned`): o gatilho operacional
desta recuperação é somente o primeiro **PLAY** elegível da VSL do Vigor 360.

A etapa documentada neste ADR implementa apenas backend, persistência e testes.
O WordPress e a VSL ainda não foram alterados para emitir o evento.

## Decisão

O backend expõe `POST /recovery/video-play`. Na V1, a identidade é aceita
exclusivamente no formato `src=mc_<manychat_id>`. O navegador nunca fornece um
e-mail confiável: o endpoint localiza o contato por `manychat_id` e obtém o
e-mail exclusivamente de `leads_vigor`.

Leads inexistentes, sem e-mail válido ou com `status_pagamento` em
`STATUS_PAGOS` são inelegíveis. Em particular, comprador nunca recebe a tag de
recuperação. Para leads elegíveis, o backend aplica no Kit a tag
`recuperacao-pos-clique-vigor360`.

O fluxo de compra permanece separado. Uma compra aplica `Comprador Vigor 360`,
que remove o contato da sequência de recuperação no Kit. Essa regra não deve
ser confundida com o fluxo de abandono de checkout.

## Idempotência e estado operacional

A tabela `recovery_video_plays` registra uma linha única por `manychat_id` e usa
os estados:

- `processing`: uma tentativa está em andamento;
- `completed`: a tag foi aplicada com resposta de sucesso e o estado é terminal;
- `failed`: a tentativa falhou e pode ser retomada posteriormente.

Um `processing` recente bloqueia concorrência e reentrada. Um `processing` cujo
`updated_at` tenha mais de 5 minutos é considerado stale e pode ser readquirido
atomicamente. Isso evita bloqueio permanente quando a atualização posterior
para `completed` ou `failed` não chega ao Supabase.

Não existe garantia de exactly-once distribuída entre Supabase e Kit. Se o Kit
aplicar a tag e a resposta HTTP se perder, um retry pode reaplicar a mesma tag.
A V1 adota entrega at-least-once com deduplicação local e aproveita a natureza
idempotente da associação da mesma tag no Kit.

A unicidade atual é por `manychat_id`; portanto, cada lead entra nessa
recuperação uma única vez na V1 depois que alcança `completed`.

## Limites e consequências

- A falha da recuperação nunca pode impedir o vídeo de tocar.
- Não há worker, scheduler, fila ou envio direto de e-mails pelo backend.
- `journey_events` não é usado como mecanismo operacional desta recuperação.
- Token assinado e `journey_run_id` na URL da VSL ficam como hardening futuro.
- O WordPress/VSL ainda precisa ser integrado em uma etapa posterior, preservando
  o comportamento atual do player e do botão `.botao-vigor`.

