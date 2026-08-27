# LUCASBOT — External Requests

> **DOCUMENTAÇÃO — NÃO EXECUTÁVEL**  
> Este arquivo documenta os contratos HTTP usados pela implementação atual. Não altera endpoints nem comportamento do backend.

**Versão de referência:** 27/08/2026  
**Base URL atual observada:** `https://lucasbot-backend.onrender.com`

## 1. Objetivo

Registrar as chamadas HTTP feitas pelo ManyChat ao backend atual, sua finalidade, payload e papel na futura migração.

Este documento deve ser lido junto com:

- `LUCASBOT_LOGICA_MESTRE.md`
- `LUCASBOT_MODELO_DE_DADOS.md`
- `LUCASBOT_ESPECIFICACAO_MIGRACAO.md`

## 2. Resumo dos contratos

| Endpoint | Papel |
|---|---|
| `POST /journey/run` | cria um `journey_run_id` para uma execução do funil |
| `POST /journey/event` | registra telemetria append-only da jornada |
| `POST /webhook` | persiste/atualiza o estado consolidado do lead em `leads_vigor` |
| `POST /tracking/claim` | tracking/claim de entrada e mensagens livres/fallback |
| `POST /kiwify` | recebe eventos de checkout/compra e reconcilia pagamento/tracking |

## 3. POST /journey/run

### Finalidade

Criar um identificador UUID v4 para uma nova passagem pelo funil.

### Corpo

Vazio.

### Resposta

```json
{
  "journey_run_id": "<uuid>"
}
```

No ManyChat, essa resposta é mapeada para a variável/campo usado para acompanhar a mesma execução durante as etapas seguintes.

### Observações

- não cria lead;
- não persiste por si só um registro de execução;
- serve para correlacionar eventos da mesma passagem pelo funil.

## 4. POST /journey/event

### Finalidade

Registrar telemetria histórica da jornada em `journey_events`.

### Eventos aceitos pelo backend

- `step_started`
- `step_answered`
- `fallback_triggered`
- `email_captured`
- `offer_clicked`
- `checkout_started`
- `purchase`

### Contrato

Campos aceitos pelo backend:

```json
{
  "lead_id": "<opcional>",
  "journey_run_id": "<uuid opcional>",
  "manychat_id": "<obrigatorio>",
  "event_name": "<obrigatorio>",
  "event_stage": "<opcional>",
  "event_value": "<opcional>",
  "source_system": "<obrigatorio>",
  "metadata": {},
  "dedupe_key": "<obrigatorio>"
}
```

### Idempotência

`dedupe_key` é a chave de idempotência do histórico.

Se o banco responder conflito de unicidade (`23505`) para a mesma `dedupe_key`, o backend trata o evento como **aceito e idempotente**, em vez de como erro lógico.

### Regra arquitetural

Telemetria é **best-effort**. Uma falha em `journey_events` não deve interromper a jornada principal do usuário.

## 5. POST /webhook

### Finalidade

Persistir/atualizar o estado consolidado do lead em `leads_vigor`.

### Identidade

`manychat_id` é obrigatório na implementação atual.

Sem um `manychat_id` válido, o endpoint retorna erro e não executa o upsert normal.

### Campos permitidos observados no backend

```text
email
nome
telefone
telefone_whatsapp
telefone_checkout_kiwify
score
idade
risco
status_jornada
tag
origem
campanha
status_testosterona
tempo_sintoma
manychat_id
status_pagamento
produto
checkout_src
checkout_utm_source
checkout_utm_medium
checkout_utm_campaign
checkout_utm_content
checkout_utm_term
origem_compra
```

### Sanitização

O backend:

- ignora valores vazios;
- ignora `none`, `null`, `undefined`;
- ignora placeholders quebrados do ManyChat como `{{...}}`;
- converte `idade` e `score` para inteiro;
- normaliza campos de telefone para dígitos;
- descarta chaves que não pertencem à lista permitida.

### Persistência

O endpoint faz upsert em `leads_vigor` usando conflito por `manychat_id`.

### E-mail / Kit

Se o upsert for bem-sucedido e houver e-mail válido, o backend agenda em background a inclusão do lead na tag de lead do Kit/ConvertKit.

Essa ação não deve atrasar nem quebrar a resposta principal do webhook.

## 6. POST /tracking/claim

### Uso confirmado no fallback

```json
{
  "manychat_id": "<ID do contato>",
  "message": "<Última Entrada de Texto>"
}
```

### Finalidade

Registrar/reconciliar mensagem livre e tracking conforme a implementação atual.

Na configuração modular de referência, depois do claim o fluxo segue para `00 — Redirecionar Etapa Atual`.

## 7. POST /kiwify

### Finalidade

Receber eventos da Kiwify e reconciliar:

- lead/identidade;
- telefone/e-mail;
- status de pagamento;
- produto;
- `src` e UTMs;
- origem da compra;
- tags de abandono/comprador no Kit;
- tag `comprou-vigor360` no ManyChat quando a identidade é resolvida.

### Regra crítica

Pagamento confirmado é terminal para fins de recuperação comercial.

Se um lead já estiver com status pago e chegar posteriormente um evento de abandono atrasado, o backend não deve rebaixar o comprador para abandonado.

## 8. Requests confirmados por módulo

### 00 — Início

Há request de persistência/tracking inicial com dados de entrada do contato, incluindo origem/campanha e demais campos pertinentes à inicialização.

Evidência visual da configuração original foi arquivada no Google Drive na pasta `Externa Requests`.

### 01 — Idade

#### External Request 1

```text
POST /journey/run
body: vazio
```

Resposta `journey_run_id` é mapeada de volta para o ManyChat.

#### Demais requests

A etapa usa os contratos semânticos:

1. registrar início da etapa em `/journey/event`;
2. persistir `idade`/estado relevante em `/webhook`;
3. registrar resposta da etapa em `/journey/event`.

### 02 — Tempo dos sintomas

A etapa usa os mesmos três papéis:

1. `step_started`;
2. persistência de `tempo_sintoma`/score no estado consolidado;
3. `step_answered`.

### 03 — Fator de risco

A implementação visual usa `fator_risco`, mas o contrato persistido pelo backend usa **`risco`**.

Adapter conceitual:

```text
ManyChat fator_risco → backend risco
```

A etapa também registra início e resposta em `/journey/event`.

### 04 — Status testosterona

Persiste `status_testosterona` e registra telemetria de início/resposta.

### 05 — E-mail

Persiste e-mail em `/webhook` e registra telemetria da etapa.

### 05R — Retomar E-mail

Payload confirmado:

```json
{
  "manychat_id": "<ID do contato>",
  "email": "<E-mail>"
}
```

Destino: `/webhook`.

### 06 — Parte Final

Os requests finais cobrem:

- persistência consolidada do lead;
- score/estado final;
- telemetria da conclusão;
- continuidade da jornada comercial.

## 9. Separação semântica obrigatória

### Estado consolidado

```text
/webhook
→ leads_vigor
→ "qual é o estado atual deste lead?"
```

### Histórico

```text
/journey/event
→ journey_events
→ "o que aconteceu durante esta execução?"
```

Esses dois conceitos não devem ser fundidos na migração.

## 10. Funções semânticas recomendadas na página futura

Em vez de copiar blocos amarelos do ManyChat, a página deve expor funções com intenção explícita:

```text
createJourneyRun()
recordJourneyEvent()
persistLeadState()
claimTracking()
processCheckoutEvent()
```

## 11. Contratos críticos

Não alterar na primeira migração sem revisão/testes específicos:

- `/webhook`
- `/kiwify`
- tracking
- `leads_vigor`
- `click_sessions`
- `journey_events`

A primeira página deve **reproduzir** os contratos atuais. Simplificações estruturais podem vir depois, em uma fase separada.

## 12. Fonte de evidência

Os screenshots da configuração original do ManyChat estão arquivados no Google Drive, pasta `Externa Requests`.

A documentação técnica no GitHub é a interpretação semântica/versionada desses contratos; os screenshots devem permanecer arquivados como evidência da implementação original.
