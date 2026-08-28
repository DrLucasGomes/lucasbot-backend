# ADR-005: Classificacao de `origem_compra` para QR Codes

## Status

Aceito.

## Contexto

O webhook `/kiwify` ja persiste `checkout_src`, `checkout_utm_source`, `checkout_utm_medium`, `checkout_utm_campaign`, `checkout_utm_content`, `checkout_utm_term` e `origem_compra` em `leads_vigor`.

A primeira compra de teste originada por `pdf101` chegou corretamente com:

- `checkout_src=qr_pdf101`;
- `checkout_utm_source=pdf`;
- `checkout_utm_medium=qrcode`;
- `checkout_utm_campaign=vigor_pdf_101`;
- `checkout_utm_content=pdf101`;
- `checkout_utm_term=<token unico>`;
- `status_pagamento=paid`.

Entretanto, a regra antiga de `classificar_origem_compra` nao conhecia PDF nem diferenciava QR de acesso direto. O resultado foi `origem_compra=rastreado_outro`, apesar de todo o tracking detalhado estar correto.

## Decisao

Nao criar uma nova coluna.

A coluna existente `origem_compra` continua sendo a classificacao resumida da aquisicao, enquanto os campos `checkout_*` preservam os dados detalhados.

A funcao `classificar_origem_compra` passa a receber tambem `utm_medium` e a classificar QR por canal:

- `youtube_qrcode`;
- `facebook_qrcode`;
- `instagram_qrcode`;
- `pdf_qrcode`;
- `qrcode_outro`.

A deteccao considera QR quando:

- `checkout_utm_medium=qrcode`; ou
- `checkout_src` comeca por `qr_`.

Os prefixos `qr_yt`, `qr_fb`, `qr_ig` e `qr_pdf` funcionam como fallback quando `utm_source` estiver ausente.

## Compatibilidade

As classificacoes nao-QR permanecem compativeis:

- `manychat`;
- `youtube_direto`;
- `facebook_direto`;
- `instagram_direto`;
- `pagina_vendas`;
- `rastreado_outro`;
- `desconhecida`.

Foi adicionada ainda `pdf_direto` para uma origem PDF rastreada que nao use QR.

A assinatura de `classificar_origem_compra` mantem `utm_medium=None` como padrao, evitando quebrar chamadas legadas com dois argumentos.

## Precedencia

`manychat` tem precedencia sobre a classificacao QR. Isso evita que um payload inconsistente com `utm_source=manychat` e `utm_medium=qrcode` seja reclassificado como QR.

Depois de ManyChat, QR e classificado antes das origens diretas.

## Historico

A migration `sql/011_backfill_qr_origem_compra.sql` atualiza registros antigos que possuam `checkout_utm_medium=qrcode` ou `checkout_src` iniciado por `qr_`.

Ela e idempotente e nao cria schema novo.

## Consequencias

Relatorios podem usar `origem_compra` para uma visao simples de canal + meio e continuar usando os campos `checkout_*` para analise detalhada.

Exemplo:

- `origem_compra=pdf_qrcode` identifica rapidamente a categoria;
- `checkout_utm_content=pdf101` identifica a peca;
- `checkout_utm_term=<token>` identifica o scan individual;
- `click_sessions.token=<mesmo token>` fecha a atribuicao exata.

Isso evita redundancia de schema e mantem a atribuicao auditavel.
