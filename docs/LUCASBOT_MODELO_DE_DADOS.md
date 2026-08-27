# LUCASBOT — Modelo de Dados

> **DOCUMENTAÇÃO — NÃO EXECUTÁVEL**  
> Este arquivo documenta a semântica dos dados usados pelo LucasBot. Não cria tabelas, não altera schemas e não modifica o backend.

**Versão de referência:** 27/08/2026

## 1. Objetivo

Mapear os principais campos usados entre ManyChat, backend e Supabase para permitir manutenção e futura migração sem perda de significado.

## 2. Identificadores

### `manychat_id`

- origem: ManyChat;
- função: identidade principal do contato na implementação atual;
- backend: obrigatório em `/webhook`;
- Supabase: chave de conflito usada no upsert de `leads_vigor`;
- migração futura: substituir gradualmente por identificador interno estável, preservando `manychat_id` como chave legada enquanto houver histórico ou integrações dependentes.

### `journey_run_id`

- origem: `POST /journey/run`;
- formato: UUID;
- função: identificar uma passagem do contato pelo funil;
- acompanha eventos de idade, tempo de sintomas, fator de risco, testosterona, e-mail e parte final;
- migração futura: manter o conceito de UUID por execução.

### `dedupe_key`

- função: idempotência de `journey_events`;
- deve ser estável por evento lógico;
- duplicata deve ser interpretada como evento já processado, não como novo evento.

## 3. Autoridade dos dados

### Estado consolidado

`leads_vigor` responde à pergunta:

> Qual é o estado atual conhecido deste lead?

### Histórico

`journey_events` responde à pergunta:

> O que aconteceu durante esta execução da jornada?

### Estado de interface/orquestração

`etapa_atual` existe no ManyChat como ponteiro operacional da conversa. Não é, por si só, a fonte de verdade do perfil consolidado do lead.

Na página futura, o equivalente recomendado é `current_step` em uma sessão/máquina de estados controlada pela aplicação.

## 4. Estado da jornada

### `etapa_atual`

Valores observados:

- `idade`
- `tempo_sintoma`
- `fator_risco`
- `status_testosterona`
- `email`
- `concluida`

Migração recomendada:

```text
ManyChat etapa_atual → application current_step
```

Não é necessário criar uma coluna no banco apenas para imitar o ManyChat. Persistir estado de sessão só se houver valor real para recuperação da jornada.

### `status_jornada`

Estado macro do contato no funil.

Valores observados no histórico do projeto incluem estados intermediários e conclusão de captura.

### `segmento_lead`

Semântica:

- incompleto durante a jornada;
- lead quente / Vigor 360 ao final quando `score >= 5`;
- lead frio quando `score <= 4`.

## 5. Dados de triagem

### `idade`

- tipo: inteiro;
- entrada: resposta digitada;
- backend: aceito em `/webhook` e convertido para inteiro;
- persistência: `leads_vigor.idade`;
- score: `> 50 = +2`, `<= 50 = +0`.

### `tempo_sintoma`

- tipo: texto categórico;
- valores de referência:
  - `< 3 meses`
  - `3–12 meses`
  - `> 1 ano`
- backend: aceito em `/webhook`;
- persistência: `leads_vigor.tempo_sintoma`;
- score: `> 1 ano = +3`, demais `+0`.

### `fator_risco` / `risco`

- ManyChat: campo visual `fator_risco`;
- valores: `Sim` / `Não`;
- backend: contrato persistido usa `risco`;
- score: `Sim = +3`, `Não = +0`.

Adapter legado:

```text
risk_factor interno
→ risco no /webhook
```

Na nova arquitetura, usar um único nome canônico internamente e manter adapter para o contrato legado.

### `status_testosterona`

- valores de referência:
  - `Baixa Confirmada`
  - `Desconfio / Normal`
- backend: aceito em `/webhook`;
- persistência: `leads_vigor.status_testosterona`;
- score: `Baixa Confirmada = +2`, demais `+0`.

### `score`

- tipo: inteiro;
- inicialização: `0`;
- máximo atual: `10`;
- composição:
  - idade: 2
  - tempo de sintomas: 3
  - fator de risco: 3
  - testosterona: 2
- segmentação:
  - `>= 5` → quente
  - `<= 4` → frio

### Regra de autoridade do score

Na futura página, o score deve ser **derivado deterministicamente das respostas**, e não depender de múltiplos incrementos frágeis da interface.

A aplicação deve impedir que a mesma etapa some pontos duas vezes.

## 6. Contato

### `email`

- capturado no módulo 05 ou 05R;
- persistido por `/webhook`;
- quando o upsert é bem-sucedido e o e-mail é válido, o backend agenda inclusão na tag de lead do Kit/ConvertKit.

### `nome`

- pode chegar em payloads de lead/checkout;
- usado para `first_name` no Kit quando disponível.

### Telefones

Campos atuais relevantes:

- `telefone`
- `telefone_whatsapp`
- `telefone_checkout_kiwify`

O backend normaliza telefone para dígitos e usa esses campos também em estratégias de reconciliação de identidade.

## 7. Origem e campanha

### `campanha`

- recebe identificador/código de entrada;
- usado para inferir o canal de origem no início do fluxo.

### `origem`

Canal de procedência do lead.

Exemplos observados:

- YouTube
- YouTube Shorts
- Instagram
- TikTok
- Facebook
- Blog
- WhatsApp Direto

Persistido no Supabase pelo backend.

### Regra TikTok corrigida

Na versão de referência, TikTok é identificado a partir de `campanha`, e não de um campo `origem` previamente limpo.

## 8. Checkout e compra

### `status_pagamento`

Estados observados no backend:

Pagos:

- `paid`
- `approved`
- `order_approved`

Abandono:

- `abandoned`
- `cart_abandoned`

Outros fluxos podem usar estados adicionais, como espera de PIX, conforme contratos específicos.

### Regra terminal de compra

Se o estado atual já é pago, um evento posterior de abandono **não pode rebaixar** o lead para abandonado.

### `produto`

Nome/identificador do produto recebido da Kiwify.

### Tracking de checkout

Campos atuais:

- `checkout_src`
- `checkout_utm_source`
- `checkout_utm_medium`
- `checkout_utm_campaign`
- `checkout_utm_content`
- `checkout_utm_term`
- `origem_compra`

Usados para atribuição e reconciliação da compra.

## 9. Tags relevantes

### `Lead_Curioso_Abandono`

Usada durante a jornada/recuperação comercial na implementação atual.

### `comprou-vigor360`

- aplicada no ManyChat pelo backend quando `/kiwify` confirma pagamento e resolve a identidade do contato;
- usada para evitar follow-up de não comprador em quem já comprou.

Na migração, tags operacionais do ManyChat devem ser substituídas por estados/eventos internos quando possível.

## 10. Modelo canônico recomendado para a página futura

Exemplo conceitual:

```text
lead_id                → identificador interno estável
legacy_manychat_id     → referência legada
journey_run_id         → UUID da execução
current_step           → estado da sessão
age                    → idade
symptom_duration       → tempo_sintoma
risk_factor            → fator de risco
status_testosterona    → status hormonal
email                  → email
score                  → valor derivado
segment                → quente/frio
source                 → origem
campaign               → campanha
payment_status         → status de pagamento
```

Adapters preservam contratos atuais:

```text
risk_factor → risco no /webhook
legacy_manychat_id → manychat_id enquanto necessário
current_step → etapa_atual apenas quando integração legada exigir
```

## 11. Princípio de migração de dados

A futura página deve ter um **modelo interno canônico** e adapters para contratos legados.

Não propagar nomes históricos inconsistentes para o novo domínio só porque existem no ManyChat.

Preservar legado para compatibilidade; não transformá-lo em desenho permanente da nova arquitetura.
