# ADR-004: QR Code rastreavel para a VSL

## Status

Aceito.

## Contexto

O Lucas Tracking ja possui `/r/{codigo}` para registrar origem em `click_sessions` antes de abrir o WhatsApp. A VSL do Protocolo Vigor 360, por sua vez, ja preserva `src` e UTMs no clique para a Kiwify, e `/kiwify` persiste esses parametros em `leads_vigor`.

Precisamos usar QR Codes em videos e outras pecas sem misturar esse fluxo com o redirecionamento para WhatsApp e sem perder a capacidade de atribuir vendas ao video/QR de origem.

## Decisao

Criar uma rota adicional `GET /v/{codigo}` usando os mesmos codigos curtos aceitos pelo tracking atual (`ytNNN`, `fbNNN`, `igNNN`).

A rota:

1. interpreta o codigo com a mesma semantica de origem/campanha/video usada por `/r/{codigo}`;
2. troca `utm_medium` para `qrcode`;
3. cria uma nova `click_session` com token imprevisivel;
4. tenta persistir essa sessao no Supabase;
5. redireciona para a VSL com:
   - `src=qr_<codigo>` para agregacao estavel por QR/video;
   - `utm_source=<canal>`;
   - `utm_medium=qrcode`;
   - `utm_campaign=vigor_<canal>_<numero>`;
   - `utm_content=<codigo>`;
   - `utm_term=<token da click_session>` para atribuicao do scan individual;
6. preserva query string preexistente na URL base da VSL.

A URL base e configuravel por `VSL_URL`, com fallback para `https://drlucasgomes.com.br/protocolo-vigor-360/`.

## Invariantes

- `/r/{codigo}` continua abrindo WhatsApp e nao muda de contrato.
- `/v/{codigo}` nunca deve depender de `WHATSAPP_NUMBER`.
- falha de persistencia da `click_session` nao deve impedir o acesso a VSL; perder telemetria e preferivel a perder a visita/venda;
- codigo invalido continua retornando 404;
- configuracao invalida de `VSL_URL` falha fechada com 503, evitando open redirect;
- `src` deve permanecer estavel por codigo e nao carregar o token individual;
- o token individual deve seguir em `utm_term`, campo que a VSL ja repassa e `/kiwify` ja persiste em `checkout_utm_term`;
- nao criar nova tabela nem alterar contratos de `/webhook` ou `/kiwify` para esta V1.

## Consequencias

Passamos a poder medir por codigo de QR:

- scans/cliques em `click_sessions`;
- origem, campanha e video;
- vendas atribuidas via `checkout_utm_source`, `checkout_utm_medium`, `checkout_utm_campaign` e `checkout_utm_content`;
- quando `checkout_utm_term` estiver presente, associacao da compra ao token exato da `click_session`.

Essa decisao reaproveita a infraestrutura existente e mantem tracking como camada adicional, sem colocar o acesso a VSL no caminho critico do Supabase.
