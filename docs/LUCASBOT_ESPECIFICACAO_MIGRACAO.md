# LUCASBOT — Especificação de Migração

> **DOCUMENTAÇÃO — NÃO EXECUTÁVEL**  
> Este arquivo define como reproduzir o LucasBot fora do ManyChat sem alterar a lógica funcional nem quebrar contratos críticos do backend.

**Versão de referência:** 27/08/2026

## 1. Princípio central

O ManyChat é a implementação atual. A fonte de verdade funcional passa a ser a documentação técnica versionada nesta pasta.

A migração deve reproduzir **comportamento e contratos**, não a aparência dos blocos do ManyChat.

## 2. Escopo da futura página

A página deve reproduzir:

- coleta sequencial de idade, tempo de sintomas, fator de risco, status de testosterona e e-mail;
- score atual;
- segmentação quente/frio;
- persistência do lead;
- telemetria de jornada;
- tracking/origem/campanha;
- continuidade da VSL/checkout/Kit/Kiwify;
- recuperação de sessão;
- prevenção determinística de submissões duplicadas.

## 3. Arquitetura alvo

```text
Frontend web
→ session / journey state
→ validação da etapa
→ motor de score
→ adapters HTTP
→ backend existente
→ Supabase
→ telemetria
→ Kit / Kiwify / tracking
```

## 4. Mapeamento ManyChat → página

| ManyChat | Página futura |
|---|---|
| `etapa_atual` | `current_step` / estado de sessão |
| Custom User Fields | modelo canônico de sessão/lead |
| Condition blocks | funções puras de decisão |
| Increase score | função determinística de scoring |
| Start Automation | `nextStep()` |
| Fallback | validação explícita + recuperação de sessão |
| External Request | funções HTTP semânticas |
| Tags | estados/eventos internos quando possível |

## 5. Máquina de estados recomendada

```text
START
→ AGE
→ SYMPTOM_DURATION
→ RISK_FACTOR
→ TESTOSTERONE_STATUS
→ EMAIL
→ RESULT
→ COMPLETED
```

Estados auxiliares devem ser mínimos e explícitos.

Não reproduzir `processando_*` como solução de concorrência.

## 6. Motor de score de referência

```text
idade > 50                       → +2
idade <= 50                      → +0
tempo > 1 ano                    → +3
demais tempos                    → +0
fator_risco = Sim                → +3
fator_risco = Não                → +0
status_testosterona = Confirmada → +2
Desconfio / Normal               → +0
```

Segmentação:

```text
score >= 5 → quente
score <= 4 → frio
```

### Regra recomendada

O score deve ser recalculável a partir das respostas armazenadas.

Não depender de uma sequência irreversível de `score += N` no frontend.

## 7. Contrato conceitual de sessão

Exemplo:

```json
{
  "lead_id": "<interno>",
  "legacy_manychat_id": "<opcional>",
  "journey_run_id": "<uuid>",
  "current_step": "AGE",
  "answers": {
    "age": 51,
    "symptom_duration": null,
    "risk_factor": null,
    "status_testosterona": null,
    "email": null
  },
  "score": 2,
  "source": "YouTube",
  "campaign": "<codigo>"
}
```

A forma física pode mudar; a semântica deve permanecer.

## 8. Requisitos de blindagem

1. desabilitar botão/opção imediatamente após submissão válida;
2. cada etapa aceitar uma única resposta lógica por `journey_run_id`;
3. requests duplicados serem idempotentes;
4. não recalcular/somar score duas vezes para a mesma etapa;
5. backend validar `current_step`/`step_id` quando a nova arquitetura assumir autoridade de estado;
6. erro de telemetria não bloquear o usuário;
7. persistência operacional e telemetria permanecerem separadas;
8. refresh recuperar a etapa correta;
9. retorno após interrupção não iniciar duas execuções concorrentes;
10. resposta de etapa anterior não poder alterar etapa já concluída;
11. compra confirmada não poder ser rebaixada por abandono atrasado;
12. sessão expirada ter comportamento explícito e previsível.

## 9. Semântica dos adapters HTTP

### `createJourneyRun()`

Chama:

```text
POST /journey/run
```

Retorna e armazena `journey_run_id`.

### `recordJourneyEvent()`

Chama:

```text
POST /journey/event
```

Deve usar `dedupe_key` estável e nunca bloquear a experiência principal por falha de telemetria.

### `persistLeadState()`

Chama inicialmente o contrato legado:

```text
POST /webhook
```

Enquanto o backend atual exigir `manychat_id`, a página pode usar adapter/identidade legada para compatibilidade. A remoção dessa dependência deve ser uma fase separada.

### `claimTracking()`

Preserva o contrato atual de tracking quando necessário.

### `processCheckoutEvent()`

Permanece responsabilidade do webhook `/kiwify`.

## 10. Estratégia de migração segura

### Fase 1 — Congelar ManyChat

- manter apenas correções críticas;
- não adicionar novas funcionalidades importantes;
- considerar a versão modular restaurada como baseline.

### Fase 2 — Implementar página paralela

- reutilizar backend atual sempre que possível;
- não alterar contratos críticos na primeira versão;
- criar adapters para `/webhook`, `/journey/run`, `/journey/event` e tracking;
- implementar máquina de estados e idempotência fora do ManyChat.

### Fase 3 — Testes

Executar no mínimo:

1. fluxo normal completo;
2. idade exatamente 50;
3. menor/maior que 50;
4. cada alternativa de tempo de sintomas;
5. risco Sim/Não;
6. testosterona Confirmada/Normal;
7. entrada inválida;
8. clique duplo rápido;
9. dez cliques rápidos no mesmo botão;
10. refresh em cada etapa;
11. retomada após interrupção;
12. duplicação artificial do mesmo HTTP request;
13. falha temporária de `/journey/event`;
14. persistência correta no Supabase;
15. score máximo 10;
16. fronteira de segmentação 4/5;
17. captura de e-mail e entrada no Kit;
18. origem/campanha, inclusive TikTok;
19. CTA/VSL/checkout;
20. compra confirmada;
21. abandono depois de compra não rebaixa status;
22. identidade/reconciliação por dados legados quando necessária.

### Fase 4 — Tráfego controlado

- enviar pequena parcela dos novos leads para a página;
- comparar conversão, abandono, erros, score e persistência com ManyChat;
- aumentar gradualmente apenas após estabilidade.

### Fase 5 — Migração de leads

Preservar no mínimo:

- `manychat_id` legado;
- nome;
- telefone(s);
- e-mail;
- origem;
- campanha;
- idade;
- tempo de sintomas;
- risco/fator de risco;
- status de testosterona;
- score;
- segmento;
- status da jornada;
- status de pagamento;
- tracking relevante;
- histórico de `journey_events` quando útil.

### Fase 6 — Desligamento do ManyChat

Somente depois de confirmar que:

- novos leads entram pela página;
- recuperação de sessão funciona;
- marketing não depende de tags ManyChat essenciais;
- pagamentos continuam reconciliados;
- histórico foi exportado/preservado;
- screenshots/documentação foram arquivados;
- tráfego real validou a nova interface.

## 11. Critérios de aceitação da página

A página é equivalente ao LucasBot atual quando um lead normal:

1. entra com origem/campanha corretas;
2. recebe as mesmas perguntas na mesma ordem;
3. produz o mesmo score;
4. produz o mesmo segmento;
5. é persistido corretamente;
6. gera telemetria correlacionada por `journey_run_id`;
7. entra no Kit quando fornece e-mail;
8. segue para a mesma continuidade comercial;
9. é reconhecido corretamente após checkout/compra;
10. não sofre duplicação de etapas quando clica repetidamente.

## 12. Critério de superioridade técnica

A nova página não deve apenas reproduzir o caminho feliz. Ela deve eliminar limitações conhecidas do ManyChat:

- múltiplas execuções concorrentes do mesmo passo;
- clique repetido causando múltiplos avanços;
- fallback reentrando no fluxo em momentos inadequados;
- score dependente de efeitos colaterais da interface;
- dificuldade de recuperar estado com precisão.

## 13. Contratos críticos a preservar na primeira migração

- `POST /webhook`
- `POST /journey/run`
- `POST /journey/event`
- tracking
- `POST /kiwify`
- `leads_vigor`
- `journey_events`
- `click_sessions` e estruturas atuais de atribuição relevantes

Não simplificar esses contratos na mesma mudança que troca a interface.

Primeiro: **paridade funcional**.  
Depois: **refatoração arquitetural**.

## 14. Decisão de arquitetura

Não fazer big bang.

```text
ManyChat estável
→ página paralela
→ testes adversariais
→ tráfego pequeno
→ comparação
→ aumento gradual
→ migração de leads
→ desligamento do ManyChat
```

O objetivo é sair do ManyChat sem transformar a migração em uma reescrita simultânea de interface, backend, dados, checkout e marketing.
