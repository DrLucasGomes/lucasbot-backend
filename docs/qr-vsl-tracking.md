# Tracking de QR para a VSL

## Objetivo

Permitir que QR Codes usados em YouTube, Shorts, Instagram e Facebook levem diretamente à VSL do Protocolo Vigor 360 sem perder a atribuição de origem.

## Rotas

- `GET /r/{codigo}` continua exclusivo do fluxo já existente `click_sessions -> WhatsApp`.
- `GET /v/{codigo}` registra o escaneamento/clique em `click_sessions` e redireciona para a VSL.

Os códigos aceitos continuam no formato `yt101`, `fb108` e `ig22`.

## Atribuição do QR

Para `/v/{codigo}`, o registro em `click_sessions` usa:

- `utm_source`: `youtube`, `facebook` ou `instagram`;
- `utm_medium=qrcode`;
- `utm_campaign=vigor_<canal>_<numero>`;
- `utm_content=<codigo>`, por exemplo `yt101`.

No redirecionamento para a VSL, `src` identifica o QR/campanha de forma estável e `utm_term` transporta o token único daquele registro em `click_sessions`.

Exemplo conceitual:

`/v/yt101 -> VSL?src=qr_yt101&utm_source=youtube&utm_medium=qrcode&utm_campaign=vigor_yt_101&utm_content=yt101&utm_term=<token>`

A VSL já preserva `src` e UTMs no botão de checkout. O webhook `/kiwify` já persiste esses valores em `checkout_src` e `checkout_utm_*`.

Isso permite duas leituras:

1. conversão agregada por QR/vídeo usando `src`, `utm_content` e `utm_campaign`;
2. futura ligação exata entre uma venda e um escaneamento específico comparando `checkout_utm_term` com `click_sessions.token`.

## Disponibilidade

O destino padrão é:

`https://drlucasgomes.com.br/protocolo-vigor-360/`

Pode ser sobrescrito por `VSL_URL` no ambiente. A URL precisa usar `http` ou `https` e possuir host válido.

## Política de falha

No fluxo `/v/{codigo}`, falha ou timeout do Supabase não bloqueia o acesso à VSL. O erro é registrado em log e o visitante continua para a página.

Essa escolha é deliberada: uma indisponibilidade temporária de telemetria não deve provocar perda de visita ou venda.

A rota `/r/{codigo}` não foi alterada e mantém o comportamento anterior.

## Métrica principal

Para cada código, a conversão básica pode ser calculada como:

`compras atribuídas ao código / registros em click_sessions do código`

Exemplo: `yt101` pode ser usado em um único vídeo para medir escaneamentos, checkouts e vendas daquele conteúdo.
