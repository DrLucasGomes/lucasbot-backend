# LUCASBOT — Lógica Mestre

> **DOCUMENTAÇÃO — NÃO EXECUTÁVEL**  
> Este arquivo descreve a lógica funcional do LucasBot. Não altera comportamento do backend, banco, Render, Supabase, Kit, Kiwify ou ManyChat.

**Versão de referência:** 27/08/2026  
**Implementação atual:** ManyChat + backend FastAPI + Supabase + Kit/Kiwify  
**Objetivo:** registrar a lógica do LucasBot de forma independente da plataforma atual e servir como fonte de verdade para manutenção e futura migração para página própria.

## 1. Regra de segurança

A configuração de referência é a **versão modular original restaurada em 27/08/2026**.

Foram mantidas apenas duas correções objetivas:

1. idade: `> 50` recebe +2 e `<= 50` recebe +0, cobrindo exatamente 50 anos;
2. TikTok: a origem é inferida a partir de `campanha`, como nos demais canais.

As tentativas experimentais com estados `processando_*` e alterações de fallback **não fazem parte da arquitetura de referência**.

## 2. Fluxo principal

```text
00 — Início
→ 01 — Captura Idade
→ 02 — Captura Tempo de Sintomas
→ 03 — Captura Fator de Risco
→ 04 — Captura Status da Testosterona
→ 05 — Captura E-mail
→ 06 — Parte Final
```

Fluxos auxiliares:

- `00 — Redirecionar Etapa Atual`
- `05R — Retomar E-mail`
- `Fallback — Mensagem Aleatória`

## 3. Estado operacional no ManyChat

`etapa_atual` funciona como ponteiro de estado da jornada na implementação atual.

Valores observados:

- `idade`
- `tempo_sintoma`
- `fator_risco`
- `status_testosterona`
- `email`
- `concluida`

`etapa_atual` é **estado de orquestração do ManyChat**. Não deve ser confundido com o estado consolidado do lead no banco.

## 4. Roteador de recuperação

`00 — Redirecionar Etapa Atual` encaminha o contato conforme `etapa_atual`:

- `idade` → 01 Idade
- `tempo_sintoma` → 02 Tempo de Sintomas
- `fator_risco` → 03 Fator de Risco
- `status_testosterona` → 04 Testosterona
- `email` → 05 E-mail
- outro/desconhecido → 00 Início

## 5. Módulo 00 — Início

Ao iniciar uma nova jornada, a implementação atual limpa campos anteriores relacionados a campanha, fator de risco, idade, origem, `journey_run_id`, score, segmento, status da jornada, testosterona e tempo de sintomas.

O score começa em `0`.

`campanha` recebe o identificador/código de entrada e `origem` é classificada a partir dele.

Canais observados:

- YouTube
- YouTube Shorts
- Instagram
- TikTok
- Facebook
- Blog
- WhatsApp Direto

Após o aceite do usuário, `etapa_atual = idade` e a triagem começa.

## 6. Módulo 01 — Idade

Pergunta de referência:

> Qual sua idade? (Digite somente números)

Entrada: número inteiro.

Score:

- `idade > 50` → `+2`
- `idade <= 50` → `+0`

Destino: `02 — Tempo de Sintomas`.

## 7. Módulo 02 — Tempo dos sintomas

Pergunta sobre há quanto tempo a função sexual começou a falhar/perder pressão.

Opções e score:

- `< 3 meses` → `+0`
- `3–12 meses` → `+0`
- `> 1 ano` → `+3`

Antes de processar a resposta, a implementação atual valida se `etapa_atual` ainda corresponde à etapa esperada. Cliques antigos são desviados para recuperação/redirecionamento.

Destino: `03 — Fator de Risco`.

## 8. Módulo 03 — Fator de risco

Pergunta: convivência com Diabetes, Pressão Alta ou Obesidade.

- `Sim` → `fator_risco = Sim` → `+3`
- `Não` → `fator_risco = Não` → `+0`

Há validação da etapa antes de aceitar a resposta.

Destino: `04 — Status da Testosterona`.

## 9. Módulo 04 — Status da testosterona

Pergunta: diagnóstico de testosterona baixa ou apenas suspeita.

- `Baixa Confirmada` → `+2`
- `Desconfio / Normal` → `+0`

Há validação da etapa antes de aceitar a resposta.

Destino: `05 — E-mail`.

## 10. Módulo 05 — E-mail

`etapa_atual = email`.

O sistema solicita o melhor e-mail do contato. Após captura válida, o dado é persistido pelo backend e o fluxo segue para a Parte Final.

## 11. Módulo 05R — Retomar e-mail

Usado quando o contato está em `etapa_atual = email`, mas a captura não se completa adequadamente.

Após nova captura válida, envia ao `/webhook`:

```json
{
  "manychat_id": "<id do contato>",
  "email": "<email>"
}
```

Depois segue para a Parte Final.

## 12. Fallback

Na configuração de referência:

- se `etapa_atual = email`, orienta o contato a tentar novamente e encaminha para `05R`;
- fora de `email`, registra a mensagem livre no tracking e encaminha para `00 — Redirecionar Etapa Atual`.

Esta é a lógica original estável.

**Não reproduzir** a versão experimental com `CONTINUAR` ou `processando_*`.

## 13. Módulo 06 — Parte Final

Marca a jornada como concluída, atualiza estado comercial e classifica o lead por score.

Pesos máximos:

| Componente | Pontos |
|---|---:|
| Idade | 2 |
| Tempo de sintomas | 3 |
| Fator de risco | 3 |
| Testosterona | 2 |
| **Total** | **10** |

Segmentação:

- `score >= 5` → lead quente / trilha Vigor 360
- `score <= 4` → lead frio / guia de hábitos

### Lead quente

Recebe resultado com CTA para apresentação/VSL do Vigor 360, entra na trilha de oferta e posteriormente verifica estado/tag de comprador antes de eventual follow-up.

### Lead frio

Recebe resultado sem a oferta principal e CTA para o Guia de Hábitos.

## 14. Invariantes funcionais

Na futura implementação web, estes comportamentos devem ser preservados:

1. uma etapa aceita **uma resposta lógica válida** por execução;
2. score é determinístico e não pode ser somado duas vezes para a mesma etapa;
3. o estado consolidado do lead é separado do histórico de eventos;
4. telemetria não pode bloquear o avanço da jornada;
5. o resultado final deve ser derivado do mesmo conjunto de regras de score;
6. origem/campanha devem sobreviver à migração;
7. compra confirmada é estado terminal para fins de recuperação comercial: um evento atrasado de abandono não pode rebaixar um comprador;
8. a primeira resposta válida para uma etapa deve prevalecer sobre submissões duplicadas da mesma interação.

## 15. Limitação conhecida do ManyChat

Testes adversariais mostraram que entradas extremamente rápidas e repetidas podem iniciar execuções concorrentes e duplicar mensagens/etapas.

A tentativa de neutralizar esse edge case dentro do ManyChat aumentou a complexidade e gerou efeitos colaterais. A decisão de referência é manter a versão modular estável e aceitar esse edge case enquanto a migração para página própria não ocorre.

## 16. Princípio para migração

A página futura deve preservar **a lógica**, não os blocos visuais do ManyChat.

```text
UI
→ estado da sessão
→ validação da etapa
→ resposta
→ score
→ persistência
→ telemetria
→ próxima etapa
→ resultado
```

O ManyChat é implementação atual. **A fonte de verdade funcional deve ser esta especificação.**
