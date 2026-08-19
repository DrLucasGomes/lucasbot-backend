# Caminhos críticos

## Escopo

São pontos críticos os fluxos de `/webhook`, `/kiwify`, tracking, persistência em `leads_vigor`, atribuição por `click_sessions` e instrumentação de `journey_events`.

`journey_events` é telemetria best-effort. Uma falha ao registrar evento não pode impedir o avanço do usuário, a atualização do lead, o processamento de compra ou a atribuição de tracking. Correções de telemetria não devem mudar contratos dos fluxos principais.

## Procedimento seguro de mudança

Antes de alterar um ponto crítico:

1. Crie uma branch dedicada.
2. Rode `pytest` e confirme a linha de base.
3. Faça a mudança com o menor escopo possível.
4. Rode novamente toda a suíte.
5. Revise o diff, incluindo migrations e contratos HTTP.
6. Abra um PR com riscos e evidências de teste.
7. Aguarde a CI verde antes do merge.

Para mudanças em jornada, confirme especialmente a preservação de `manychat_id`, `journey_run_id` e `dedupe_key`, o comportamento best-effort e a ausência de updates ou deletes em `journey_events`.

## Runtime de produção

Produção não deve ser movida de volta para o Render Free sem reavaliar explicitamente o risco de spin-down e cold start. Essa avaliação deve considerar a latência da primeira requisição e possíveis timeouts ou atrasos nos fluxos do ManyChat, da Kiwify e de `journey_events`.

## Recuperação pós-play da VSL

O primeiro play elegível da VSL e o abandono de checkout são gatilhos distintos.
Não misture `POST /recovery/video-play` com `cart_abandoned` nem altere o fluxo
de recuperação de checkout ao evoluir a recuperação pós-play.

Regras críticas:

- nunca confiar em e-mail enviado pelo navegador; a identidade V1 é somente
  `src=mc_<manychat_id>` e o e-mail vem de `leads_vigor`;
- não remover a proteção de `STATUS_PAGOS`: comprador é inelegível para a tag
  de recuperação pós-play;
- garantir que a migration `004_create_recovery_video_plays.sql` exista no
  Supabase antes do deploy do endpoint;
- configurar `TAG_RECUPERACAO_VIDEO_ID` no Render com o ID da tag
  `recuperacao-pos-clique-vigor360`;
- manter falhas de Supabase ou Kit fora do caminho crítico do player: a
  recuperação nunca pode impedir o vídeo de tocar;
- em alterações futuras no player, preservar o comportamento atual do vídeo e
  do botão `.botao-vigor`.

A tabela `recovery_video_plays` protege concorrência e retries por estado. Não
remova a terminalidade de `completed`, o retry de `failed` nem a recuperação de
`processing` stale após 5 minutos sem reavaliar a idempotência do fluxo.
