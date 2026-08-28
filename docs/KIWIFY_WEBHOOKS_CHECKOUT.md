# Kiwify — Documentação Técnica dos Webhooks de Checkout

**Registro técnico:** 28/08/2026  
**Status:** critérios de disparo ainda não confirmados

## Resumo executivo

A Kiwify confirmou que envia webhooks em JSON, permite selecionar eventos por produto e oferece teste/logs. Porém, não informou o critério, o tempo de espera nem a relação entre abandono de checkout, PIX pendente, boleto pendente e cartão recusado. Portanto, essas regras não devem ser presumidas no backend até validação técnica ou teste controlado.

## 1. Objetivo

Registrar, de forma permanente, o que foi confirmado pelo suporte da Kiwify, o que permanece desconhecido e quais decisões técnicas devem ser tomadas antes de automatizar sequências de recuperação de vendas.

## 2. Resposta recebida da Kiwify

> Olá! Tudo bem?
>
> Posso confirmar que a Kiwify envia webhooks em formato JSON e permite selecionar, por produto, quais eventos devem dispará-los. Também há opção de teste e consulta aos logs, incluindo requisição, resposta e reenvio em caso de falha.
>
> Não tenho informações confirmadas sobre os critérios, tempo de espera ou o momento exato do evento de abandono, nem sobre a distinção para PIX ou boleto pendentes. A documentação técnica disponível pode ajudar na configuração e nos testes.

## 3. O que está confirmado

- Os webhooks da Kiwify são enviados em formato JSON.
- É possível selecionar, por produto, quais eventos devem disparar webhooks.
- A plataforma possui função de teste do webhook.
- Há logs com requisição, resposta e possibilidade de reenvio em caso de falha.

## 4. O que NÃO foi respondido

- Qual condição transforma um checkout iniciado em “carrinho abandonado”.
- Quanto tempo decorre entre a saída do usuário do checkout e o disparo do evento de abandono.
- Se um PIX gerado e não pago também pode, posteriormente, gerar evento de abandono.
- Se um boleto gerado e não pago também pode, posteriormente, gerar evento de abandono.
- Como uma tentativa de cartão recusado se relaciona com o evento de abandono.
- Quais campos/status do JSON distinguem inequivocamente cada situação.

## 5. Interpretação técnica

**Conclusão:** a resposta do suporte não define o contrato de negócio do evento de abandono. Logo, observar um evento chegando após determinado intervalo em um teste isolado não autoriza assumir que esse é o comportamento permanente da Kiwify.

**Regra de engenharia:** não codificar delays, exclusões ou sobreposição entre eventos com base em suposição. A lógica deve ser baseada em documentação oficial inequívoca ou em testes controlados repetíveis.

## 6. Modelo desejado de estados no backend

| Situação observada | Estado/rota desejada | Ação de recuperação |
|---|---|---|
| Checkout abandonado sem pagamento | `abandoned` | Sequência específica de abandono |
| PIX gerado e pendente | `pix_pending` | Sequência específica de PIX |
| Boleto gerado e pendente | `boleto_pending` | Sequência específica de boleto |
| Cartão recusado | `card_declined` | Sequência específica de cartão recusado |
| Pagamento aprovado | `paid` | Interromper recuperações e marcar comprador |

> **Observação:** os nomes de estados acima representam a modelagem desejada no sistema e não devem ser tratados como nomes oficiais de eventos da Kiwify até que os payloads sejam confirmados.

## 7. Plano de validação caso o suporte não esclareça

Executar testes controlados, mantendo cada cenário separado e registrando os timestamps da ação no checkout, do log na Kiwify e do recebimento no endpoint próprio.

- **Teste A:** preencher os dados do checkout e sair sem selecionar/gerar meio de pagamento.
- **Teste B:** gerar PIX e não realizar o pagamento.
- **Teste C:** gerar boleto e não realizar o pagamento.
- **Teste D:** provocar uma tentativa de cartão recusado em ambiente/teste permitido pela plataforma.
- **Teste E:** concluir uma compra aprovada para verificar se eventos pendentes/recuperações devem ser cancelados.

### Dados que devem ser registrados em cada teste

- Evento recebido e payload JSON completo.
- Timestamp da ação no checkout.
- Timestamp do disparo registrado no log da Kiwify.
- Timestamp de recebimento no backend.
- Identificador de pedido/checkout/transação utilizado para correlação.
- Sequência de eventos recebidos para o mesmo checkout ao longo do tempo.

## 8. Perguntas pendentes para o suporte técnico

1. Qual é o critério exato utilizado para considerar um checkout abandonado?
2. Qual é o tempo de espera até o disparo do evento de abandono?
3. PIX gerado e não pago pode posteriormente gerar também “carrinho abandonado”?
4. Boleto gerado e não pago pode posteriormente gerar também “carrinho abandonado”?
5. Cartão recusado pode posteriormente gerar evento de abandono?
6. Quais campos/status do JSON distinguem abandono puro, PIX pendente, boleto pendente, cartão recusado e pagamento aprovado?

## 9. Decisão registrada

Até nova evidência:

- não tratar abandono, PIX pendente, boleto pendente e cartão recusado como eventos equivalentes;
- não assumir um delay fixo de abandono;
- impedir que uma compra aprovada continue recebendo comunicação de recuperação.

**Próximo passo:** aguardar resposta técnica objetiva da Kiwify. Se ela não vier, executar a matriz de testes controlados e documentar os payloads reais antes de consolidar a lógica definitiva do backend.
