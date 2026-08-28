# Tracking de QR para a VSL

## Objetivo

Permitir que QR Codes usados em YouTube, Shorts, Instagram, Facebook e materiais em PDF levem diretamente à VSL do Protocolo Vigor 360 sem perder a atribuição de origem, campanha, peça de conteúdo e, quando houver compra, do scan individual que originou a venda.

## Rotas

- `GET /r/{codigo}` continua exclusivo do fluxo `click_sessions -> WhatsApp`.
- `GET /v/{codigo}` registra o scan/clique em `click_sessions` e redireciona para a VSL.

Os códigos aceitos seguem os formatos:

- `ytNNN` - YouTube;
- `fbNNN` - Facebook;
- `igNNN` - Instagram;
- `pdfNNN` - PDF.

Exemplos: `yt101`, `fb108`, `ig22`, `pdf101`.

## Atribuição do QR

Para `/v/{codigo}`, o registro em `click_sessions` usa:

- `utm_source`: `youtube`, `facebook`, `instagram` ou `pdf`;
- `utm_medium=qrcode`;
- `utm_campaign=vigor_<canal>_<numero>`;
- `utm_content=<codigo>`, por exemplo `yt101` ou `pdf101`.

A `click_session` recebe ainda um `token` imprevisível e único.

No redirecionamento para a VSL:

- `src=qr_<codigo>` identifica o QR de forma estável para agregação;
- `utm_source`, `utm_medium`, `utm_campaign` e `utm_content` preservam a atribuição agregada;
- `utm_term=<click_sessions.token>` transporta o identificador único daquele scan.

Exemplos conceituais:

`/v/yt101 -> VSL?src=qr_yt101&utm_source=youtube&utm_medium=qrcode&utm_campaign=vigor_yt_101&utm_content=yt101&utm_term=<token>`

`/v/pdf101 -> VSL?src=qr_pdf101&utm_source=pdf&utm_medium=qrcode&utm_campaign=vigor_pdf_101&utm_content=pdf101&utm_term=<token>`

## Nuance importante: `token` x `utm_term`

Dentro de `click_sessions`, o identificador individual do scan está em `token`.

O campo `click_sessions.utm_term` pode permanecer `null`; isso é esperado no fluxo atual. Na montagem da URL da VSL, o backend copia `click_sessions.token` para o parâmetro de query `utm_term`.

A VSL preserva esse parâmetro até a Kiwify e o webhook `/kiwify` o grava em `leads_vigor.checkout_utm_term`.

A ligação exata é portanto:

`click_sessions.token = leads_vigor.checkout_utm_term`

Isso foi validado em produção em 28/08/2026.

## Persistência na compra

A VSL preserva `src` e UTMs no botão de checkout. O webhook `/kiwify` extrai os parâmetros enviados pela Kiwify e persiste em `leads_vigor`:

- `checkout_src`;
- `checkout_utm_source`;
- `checkout_utm_medium`;
- `checkout_utm_campaign`;
- `checkout_utm_content`;
- `checkout_utm_term`;
- `origem_compra`.

Não foi criada nova coluna para classificar QR. A coluna existente `origem_compra` é suficiente.

## Classificação de `origem_compra`

Para compras originadas por QR Code, a classificação passa a distinguir canal e meio:

- `youtube_qrcode`;
- `facebook_qrcode`;
- `instagram_qrcode`;
- `pdf_qrcode`;
- `qrcode_outro` para QR rastreado sem canal conhecido.

Acessos não-QR continuam usando as classificações existentes, como `youtube_direto`, `facebook_direto`, `instagram_direto`, `pagina_vendas` e `manychat`. PDF direto pode ser classificado como `pdf_direto`.

A migration `sql/011_backfill_qr_origem_compra.sql` corrige de forma idempotente registros antigos que tenham `checkout_utm_medium=qrcode` ou `checkout_src` iniciado por `qr_`.

## Tabelas e migrations

### `click_sessions`

A tabela de scans/cliques é criada por:

`sql/010_create_click_sessions.sql`

Ela armazena, entre outros campos:

- `token`;
- origem/campanha/conteúdo;
- UTMs;
- `manychat_id` quando houver claim;
- `claimed`, `claim_method`, `claim_confidence`;
- `user_agent` e hash de IP;
- `created_at`, `expires_at`, `claimed_at`.

### Backfill de origem de compra

`sql/011_backfill_qr_origem_compra.sql`

Essa migration não cria coluna. Apenas normaliza `origem_compra` para compras QR já existentes.

## Supabase e autenticação server-side

O tracking roda no backend Render e usa `SUPABASE_KEY` apenas no servidor.

Para chaves novas do Supabase no formato `sb_secret_...`, `tracking_routes.py` envia a chave no header `apikey` e não a trata como JWT em `Authorization: Bearer`.

Chaves JWT legadas continuam compatíveis com `Authorization: Bearer`.

A tabela `click_sessions` mantém RLS habilitado e acesso de escrita restrito ao `service_role`; não é necessário abrir INSERT para `anon`.

## Política de falha

No fluxo `/v/{codigo}`, falha ou timeout do Supabase não bloqueia o acesso à VSL. O erro é registrado em log e o visitante continua para a página.

Essa escolha é deliberada: uma indisponibilidade temporária de telemetria não deve provocar perda de visita ou venda.

Por isso, um `302` isolado prova que o redirecionamento funcionou, mas não prova sozinho que a `click_session` foi persistida. A confirmação deve ser feita no Supabase ou por logs de erro/sucesso do tracking.

A rota `/r/{codigo}` mantém o comportamento anterior.

## Validação em produção — `pdf101` — 28/08/2026

O fluxo completo foi validado com uma compra PIX real de teste.

URL pública usada:

`https://lucasbot-backend.onrender.com/v/pdf101`

Fluxo comprovado:

`PDF/QR -> /v/pdf101 -> click_sessions -> VSL -> checkout Kiwify -> PIX pago -> /kiwify -> leads_vigor`

Campos confirmados na Kiwify e no Supabase:

- `src=qr_pdf101`;
- `utm_source=pdf`;
- `utm_medium=qrcode`;
- `utm_campaign=vigor_pdf_101`;
- `utm_content=pdf101`;
- `utm_term=<token único do scan>`;
- `status_pagamento=paid`.

Também foi confirmado que o valor enviado à Kiwify em `utm_term` era exatamente o mesmo valor gravado anteriormente em `click_sessions.token`.

Nenhum dado pessoal do comprador, CPF, telefone, e-mail, order id ou URL de acesso deve ser colocado na documentação do repositório.

## Consultas operacionais

### Scans por peça

```sql
select
    token,
    origem,
    campanha,
    utm_source,
    utm_medium,
    utm_content,
    created_at
from public.click_sessions
where utm_content = 'pdf101'
order by created_at desc;
```

### Compras atribuídas à peça

```sql
select
    id,
    status_pagamento,
    produto,
    checkout_src,
    checkout_utm_source,
    checkout_utm_medium,
    checkout_utm_campaign,
    checkout_utm_content,
    checkout_utm_term,
    origem_compra
from public.leads_vigor
where checkout_utm_content = 'pdf101';
```

### Ligação exata scan -> compra

```sql
select
    c.token,
    c.origem as origem_scan,
    c.campanha,
    c.utm_content as codigo_qr,
    c.created_at as data_scan,
    l.id as lead_id,
    l.status_pagamento,
    l.produto,
    l.checkout_src,
    l.checkout_utm_medium,
    l.checkout_utm_content,
    l.checkout_utm_term,
    l.origem_compra
from public.click_sessions c
join public.leads_vigor l
    on l.checkout_utm_term = c.token
where c.utm_content = 'pdf101'
order by c.created_at desc;
```

## Métricas

Para cada código:

`taxa de venda por scan = compras pagas atribuídas ao código / scans em click_sessions`

A atribuição agregada usa `utm_content`, `utm_campaign`, `utm_source` e `origem_compra`.

A atribuição individual usa:

`leads_vigor.checkout_utm_term = click_sessions.token`

## Convenção operacional

Usar um código distinto por peça de conteúdo quando for necessário medir desempenho individual.

YouTube:

- `yt101`
- `yt102`
- `yt103`
- ...

PDF:

- `pdf101` - guia “7 sinais que sua ereção está enfraquecendo”;
- `pdf102` - próximo material rastreável.

Instagram e Facebook seguem a mesma lógica com `ig` e `fb`.

Cada código deve ficar associado a uma única peça sempre que o objetivo for comparar scans, checkouts e vendas por conteúdo.

## Status atual

Em 28/08/2026:

- `/v/{codigo}` está implementado para YouTube, Facebook, Instagram e PDF;
- `click_sessions` está criada e protegida;
- o tracking usa headers compatíveis com `sb_secret_`;
- `pdf101` foi validado em produção até uma compra PIX paga;
- a ligação exata `click_sessions.token = leads_vigor.checkout_utm_term` foi comprovada;
- `origem_compra` passa a distinguir QR por canal sem adicionar coluna nova.
