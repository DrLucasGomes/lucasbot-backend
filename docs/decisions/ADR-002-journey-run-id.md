# ADR-002: `journey_run_id`

- Status: aceito

## Contexto

`manychat_id` identifica uma pessoa, mas não distingue tentativas ou passagens diferentes dessa pessoa pelo funil. Análises de sequência precisam agrupar somente os eventos de uma mesma passagem completa.

## Decisão

`journey_run_id` é um UUID que identifica uma passagem completa pelo funil. O mesmo valor acompanha os eventos de `idade`, `tempo_sintoma`, `fator_risco`, `status_testosterona`, `email` e `parte_final` daquela passagem.

`POST /journey/run` apenas gera um UUID v4. Ele não persiste a execução nem valida estado do lead. O cliente que inicia a passagem deve conservar o UUID e enviá-lo em cada `POST /journey/event` relacionado.

`manychat_id` continua identificando o contato, enquanto `dedupe_key` continua identificando unicamente cada evento. A idempotência é independente do run.

## Compatibilidade e análise

`journey_run_id` é opcional para preservar a compatibilidade com eventos criados durante a transição. Eventos antigos com valor nulo permanecem no histórico, mas não devem ser usados em análises da jornada nova baseadas em uma passagem completa.

## Consequências

- Um contato pode ter vários `journey_run_id` ao longo do tempo.
- Eventos de runs distintos não devem ser combinados em uma única sequência.
- Perder ou trocar o UUID no meio do funil fragmenta a análise, embora não interrompa o fluxo operacional.
