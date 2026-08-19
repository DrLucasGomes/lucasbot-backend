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
