# Tracking de QR para a VSL

## Objetivo

Permitir que QR Codes usados em YouTube, Shorts, Instagram, Facebook e materiais em PDF levem diretamente à VSL do Protocolo Vigor 360 sem perder a atribuição de origem.

## Rotas

- `GET /r/{codigo}` continua exclusivo do fluxo já existente `click_sessions -> WhatsApp`.
- `GET /v/{codigo}` registra o escaneamento/clique em `click_sessions` e redireciona para a VSL.

Os códigos aceitos seguem os formatos `yt101`, `fb108`, `ig22` e `pdf101`.

## Atribuição do QR

Para `/v/{codigo}`, o registro em `click_sessions` usa:

- `utm_source`: `youtube`, `facebook`, `instagram` ou `pdf`;
- `utm_medium=qrcode`;
- `utm_campaign=vigor_<canal>_<numero>`;
- `utm_content=<codigo>`, por exemplo `yt101` ou `pdf101`.

No redirecionamento para a VSL, `src` identifica o QR/campanha de forma estável e `utm_term` transporta o token único daquele registro em `click_sessions`.

Exemplos conceituais:

`/v/yt101 -> VSL?src=qr_yt101&utm_source=youtube&utm_medium=qrcode&utm_campaign=vigor_yt_101&utm_content=yt101&utm_term=<token>`

`/v/pdf101 -> VSL?src=qr_pdf101&utm_source=pdf&utm_medium=qrcode&utm_campaign=vigor_pdf_101&utm_content=pdf101&utm_term=<token>`

A VSL já preserva `src` e UTMs no botão de checkout. O webhook `/kiwify` já persiste esses valores em `checkout_src` e `checkout_utm_*`.

Isso permite duas leituras:

1. conversão agregada por QR/peça usando `src`, `utm_content` e `utm_campaign`;
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

Exemplo: `yt101` pode ser usado em um único vídeo para medir escaneamentos, checkouts e vendas daquele conteúdo; `pdf101` identifica especificamente o guia PDF “7 sinais que sua ereção está enfraquecendo”.

## Validação em produção — 28/08/2026

A primeira rota de QR para a VSL foi validada em produção com o código `yt101`.

URL pública confirmada:

`https://lucasbot-backend.onrender.com/v/yt101`

O fluxo confirmado é:

`QR -> /v/yt101 -> click_sessions -> VSL com src/UTMs -> checkout Kiwify -> /kiwify -> Supabase`

Após a confirmação da rota pública, foi gerado um QR Code em preto sobre fundo branco apontando exatamente para essa URL. O arquivo foi validado por leitura automática do QR e o valor decodificado retornou exatamente:

`https://lucasbot-backend.onrender.com/v/yt101`

Isso confirma que o QR utilizado para `yt101` é funcional e aponta para a rota rastreável correta.

## QR do PDF — `pdf101`

O guia “7 sinais que sua ereção está enfraquecendo” usa um código próprio para separar sua atribuição da origem YouTube, Instagram e Facebook.

A URL definitiva do QR do guia é:

`https://lucasbot-backend.onrender.com/v/pdf101`

Quando acessada, a rota deve registrar uma `click_session` com origem `PDF`, `utm_source=pdf`, `utm_medium=qrcode`, `utm_campaign=vigor_pdf_101` e `utm_content=pdf101`, antes de redirecionar para a VSL.

O QR embutido na página 10 do PDF final deve apontar exatamente para `/v/pdf101`, permitindo medir scans, checkouts e vendas gerados especificamente pelo guia.

### Convenção operacional

Usar um código distinto por peça de conteúdo quando for necessário medir desempenho individual. Para YouTube, seguir a sequência:

- `yt101`
- `yt102`
- `yt103`
- ...

Para PDFs, usar o prefixo `pdf`, por exemplo:

- `pdf101` - guia “7 sinais que sua ereção está enfraquecendo”
- `pdf102` - próximo material rastreável

Cada código deve ser associado a uma única peça sempre que o objetivo for comparar scans, checkouts e vendas por conteúdo.

Para Instagram e Facebook, manter a mesma lógica usando os prefixos `ig` e `fb`.

### Status

Em 28/08/2026, a infraestrutura de QR rastreável para a VSL está implementada para YouTube, Instagram, Facebook e PDF. A rota `yt101` já foi confirmada em produção; `pdf101` deve ser validada após o deploy desta extensão antes da distribuição do PDF final.
