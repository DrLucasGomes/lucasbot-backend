# ADR-003: Render Starter para evitar spin-down

- Status: aceito

## Contexto

O backend `lucasbot-backend` operava no Render Free, sujeito a spin-down após períodos de inatividade e ao consequente cold start na primeira requisição. Esse atraso afetava chamadas operacionais do ManyChat, da Kiwify e o registro de `journey_events`.

## Decisão

Manter o runtime de produção no Render Starter, ao custo atual de US$ 7/mês, para conservar o backend ativo. A migração de plano não alterou a URL do serviço nem o código da aplicação.

## Motivo

Evitar que a primeira requisição após um período de inatividade sofra o atraso de inicialização do backend, reduzindo o risco de timeout ou degradação percebida nas integrações do ManyChat, da Kiwify e nos eventos de jornada.

## Consequências

- Produção passa a ter um custo mensal de US$ 7.
- O serviço deve permanecer ativo sem o spin-down característico do plano Free.
- A URL, os contratos HTTP e o código da aplicação permanecem inalterados.
- O plano de hospedagem passa a integrar os requisitos operacionais dos caminhos críticos.

## Risco de regressão

Mover produção de volta para o Render Free sem reavaliar esta decisão pode reintroduzir spin-down e cold start, aumentando a latência da primeira requisição e o risco de falhas ou atrasos nas integrações críticas.

## Como validar

- Confirmar resposta HTTP 200 do backend imediatamente após a alteração de plano. O teste inicial retornou HTTP 200 em aproximadamente 0,89 s.
- Após um período representativo de inatividade, realizar nova requisição e medir o tempo de resposta.
- Confirmar que não houve cold start perceptível nem timeout nas chamadas do ManyChat, da Kiwify e de `journey_events`.
- Registrar o resultado do teste pós-inatividade, ainda pendente, como evidência operacional desta decisão.
