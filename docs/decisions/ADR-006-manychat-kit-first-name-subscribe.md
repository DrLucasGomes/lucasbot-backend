# ADR-006: `first_name` no subscribe ManyChat -> Kit

- Status: aceito

## Contexto

No fluxo ManyChat, o email era inscrito no Kit, mas o `first_name` aparecia de
forma intermitente. A arquitetura anterior executava duas operações: primeiro
fazia `POST /v3/tags/{tag_id}/subscribe` somente com email, extraia o
`subscriber_id` da resposta e depois fazia um `PUT` separado para gravar o
`first_name`.

A API Kit v3 suporta oficialmente o envio opcional de `first_name` diretamente
no `POST /v3/tags/{tag_id}/subscribe`.

## Decisão

O fluxo ManyChat envia `api_secret`, `email` e, quando normalizado e válido,
`first_name` na mesma operação de subscribe. Quando o nome segue no POST, esse
fluxo não depende nem executa um PUT posterior para gravá-lo.

O fluxo PIX mantém sua lógica própria, incluindo o helper compartilhado de PUT,
e não foi alterado por esta decisão.

## Evidência

- 3 de 3 E2Es consecutivos na branch experimental foram bem-sucedidos;
- 1 de 1 E2E em produção após merge e deploy da `main` foi bem-sucedido;
- nos quatro casos, o `first_name` apareceu imediatamente no Kit.

Esses resultados validam a arquitetura escolhida, mas não provam qual mecanismo
interno causava a intermitência anterior. Race condition ou consistência
eventual não são registradas como causa comprovada.

## Consequências

- email e primeiro nome são enviados atomicamente pela mesma chamada do fluxo
  ManyChat;
- o caminho ManyChat deixa de depender da extração do `subscriber_id` e do PUT
  posterior para gravar o nome;
- chamadas sem nome válido preservam o payload anterior com credencial e email;
- a API v3 permanece uma dívida técnica separada; eventual migração para v4 não
  faz parte desta correção.
