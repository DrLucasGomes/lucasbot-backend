# ADR-004: QR Code rastreavel para a VSL

## Status

Aceito.

## Contexto

O Lucas Tracking ja possui `/r/{codigo}` para registrar origem em `click_sessions` antes de abrir o WhatsApp. A VSL do Protocolo Vigor 360, por sua vez, ja preserva `src` e UTMs no clique para a Kiwify, e `/kiwify` persiste esses parametros em `leads_vigor`.

Precisamos usar QR Codes em videos, redes sociais e PDFs sem misturar esse fluxo com o redirecionamento para WhatsApp e sem perder a capacidade de atribuir vendas ao conteudo/QR de origem.

## Decisao

Criar uma rota adicional `GET /v/{codigo}` usando codigos curtos de tracking (`ytNNN`, `fbNNN`, `igNNN`, `pdfNNN`).

A rota:

1. interpreta o codigo com a mesma semantica de origem/campanha/conteudo usada pelo tracking;
2. troca `utm_medium` para `qrcode`;
3. cria uma nova `click_session` com token imprevisivel;
4. tenta persistir essa sessao no Supabase;
5. redireciona para a VSL com:
   - `src=qr_<codigo>` para agregacao estavel por QR/conteudo;
   - `utm_source=<canal>`;
   - `utm_medium=qrcode`;
   - `utm_campaign=vigor_<canal>_<numero>`;
   - `utm_content=<codigo>`;
   - `utm_term=<token da click_session>` para atribuicao do scan individual;
6. preserva query string preexistente na URL base da VSL.

A URL base e configuravel por `VSL_URL`, com fallback para `https://drlucasgomes.com.br/protocolo-vigor-360/`.

## Invariantes

- `/r/{codigo}` continua abrindo WhatsApp e nao muda de contrato.
- `/v/{codigo}` nunca depende de `WHATSAPP_NUMBER`.
- falha de persistencia da `click_session` nao impede o acesso a VSL; perder telemetria e preferivel a perder a visita/venda;
- codigo invalido retorna 404;
- configuracao invalida de `VSL_URL` falha fechada com 503, evitando open redirect;
- `src` permanece estavel por codigo e nao carrega o token individual;
- o token individual segue em `utm_term`, campo que a VSL repassa e `/kiwify` persiste em `checkout_utm_term`;
- a ligacao exata e `click_sessions.token = leads_vigor.checkout_utm_term`;
- `click_sessions.utm_term` nao precisa conter o token; pode permanecer nulo;
- nao criar nova coluna para classificar QR em `leads_vigor`; reutilizar `origem_compra`.

## Consequencias

Passamos a poder medir por codigo de QR:

- scans/cliques em `click_sessions`;
- origem, campanha e conteudo;
- vendas atribuidas via `checkout_utm_source`, `checkout_utm_medium`, `checkout_utm_campaign` e `checkout_utm_content`;
- associacao exata de uma compra ao scan individual via `checkout_utm_term = click_sessions.token`.

O fluxo `pdf101` foi validado em producao em 28/08/2026 ate uma compra PIX paga, sem registrar dados pessoais do comprador na documentacao.

A classificacao de `origem_compra` para QR por canal e detalhada no ADR-005.
