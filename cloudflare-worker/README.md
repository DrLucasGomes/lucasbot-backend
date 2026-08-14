# Lucas Tracking Edge

Worker de redirect para tirar o cold start do Render do caminho critico.

## Fluxo

`go.drlucasgomes.com.br/yt101 -> Worker -> click_sessions -> WhatsApp`

O Worker replica o formato atual da tabela `click_sessions` e mantem a mensagem `VIGOR <token>` para claim exato quando o usuario nao apaga o texto.

## Variaveis

- `WHATSAPP_NUMBER`: numero internacional somente digitos ou formatado; o Worker limpa nao-digitos.
- `SUPABASE_KEY`: secret. Use a mesma chave do backend somente se ela tiver permissao de INSERT em `click_sessions`.
- `TRACKING_IP_SALT`: secret aleatorio usado para hash do IP.

Nao versione os valores de `SUPABASE_KEY` nem `TRACKING_IP_SALT`.

## Deploy por Wrangler

```bash
cd cloudflare-worker
npm create cloudflare@latest -- --help
npx wrangler secret put SUPABASE_KEY
npx wrangler secret put TRACKING_IP_SALT
npx wrangler deploy
```

Antes do deploy, defina `WHATSAPP_NUMBER` no painel da Cloudflare ou em `[vars]` no `wrangler.toml`.

## URL de teste

Com `workers.dev` habilitado:

`https://lucas-tracking-edge.<seu-subdominio>.workers.dev/yt101`

Tambem aceita `/r/yt101` para facilitar a migracao.

## Dominio definitivo

Depois do teste, vincule um Custom Domain como:

`go.drlucasgomes.com.br`

Assim os links ficam:

- `https://go.drlucasgomes.com.br/yt101`
- `https://go.drlucasgomes.com.br/fb113`
- `https://go.drlucasgomes.com.br/ig1`

## Comportamento em falha

O Worker espera ate 1,8 s pelo Supabase. Se o INSERT falhar ou estourar timeout, ele faz fail-open e ainda abre o WhatsApp. Nesse caso o header de resposta fica `X-Lucas-Tracking: degraded`; quando salva normalmente, `X-Lucas-Tracking: saved`.
