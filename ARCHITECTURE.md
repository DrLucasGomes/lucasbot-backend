# Arquitetura

## Runtime de produção

O runtime atual de produção é o Render Starter, adotado para manter o backend ativo e evitar spin-down e cold start após períodos de inatividade. A mudança de plano não alterou a URL do serviço nem o código da aplicação.

## Estado do lead e histórico da jornada

`leads_vigor` mantém o estado consolidado e atual do lead. Seus registros podem ser atualizados conforme novas informações chegam e são usados pelos fluxos operacionais existentes.

`journey_events` mantém o histórico de acontecimentos do funil. Cada acontecimento gera uma nova linha; registros existentes não são atualizados nem removidos. A tabela é, portanto, append-only.

## Identificadores

- `manychat_id` identifica o contato no ManyChat e liga suas diferentes passagens pelo funil.
- `journey_run_id` identifica uma passagem completa desse contato pelo funil. Um mesmo `manychat_id` pode ter vários runs.
- `dedupe_key` identifica unicamente um evento para tornar reenvios idempotentes. Sua unicidade é global e independe do `journey_run_id`.

O mesmo `journey_run_id` deve acompanhar os eventos de `idade`, `tempo_sintoma`, `fator_risco`, `status_testosterona`, `email` e `parte_final` durante uma passagem completa.

## Endpoints de jornada

`POST /journey/run` apenas gera e devolve um UUID v4. Ele não cria lead, não persiste run e não acessa serviços externos.

`POST /journey/event` valida o contrato e tenta inserir um evento no Supabase. Essa gravação é best-effort: indisponibilidade, timeout ou rejeição da persistência são reportados no corpo da resposta, sem quebrar o fluxo principal do funil. Uma violação de unicidade PostgreSQL `23505` é tratada como reenvio idempotente.

Eventos históricos sem `journey_run_id` são aceitos por compatibilidade. Eles representam o período de transição e não devem ser incluídos em análises da jornada nova baseadas em runs completos.

## Limites de mudança

A instrumentação de jornada é adicional. Ela não altera os contratos de `/webhook`, `/kiwify`, tracking, `leads_vigor` ou `click_sessions`.

## Disciplina de revisão

Mudanças em caminhos críticos seguem branch dedicada, auditoria adversarial no VS Code/Codex, suíte completa de testes, revisão de diff e atualização documental antes do merge. A revisão do Codex é usada como segunda camada para procurar regressões, concorrência, falhas de ordenação, idempotência incompleta e efeitos externos duplicados; ela não substitui testes E2E reais.

## Recuperação após o play da VSL

`POST /recovery/video-play` é o gatilho operacional do primeiro play elegível da VSL do Vigor 360. Esse fluxo é independente do clique no checkout e de `cart_abandoned`.

Na V1, o endpoint aceita identidade exclusivamente por `src=mc_<manychat_id>`. O e-mail não é aceito do navegador: ele é obtido de `leads_vigor`. Leads sem e-mail válido, inexistentes ou com `status_pagamento` em `STATUS_PAGOS` não recebem a tag `recuperacao-pos-clique-vigor360` no Kit.

A VSL está integrada à YouTube IFrame API e dispara o endpoint apenas no primeiro estado real `PLAYING` elegível. O endpoint aceita CORS dos hosts oficiais do site. Falha de tracking não interfere no player.

O estado operacional e a deduplicação ficam em `recovery_video_plays`, com uma linha única por `manychat_id`. `completed` é terminal, `failed` pode ser retomado e `processing` pode ser readquirido atomicamente quando estiver stale há mais de 5 minutos. A integração é at-least-once com deduplicação local, sem garantia de exactly-once entre Supabase e Kit.

A tag inicia no Kit a sequência `Vigor 360 — Recuperação Pós-Clique`, com cadência definitiva: 1 hora até o E-mail 1, mais 1 dia até o E-mail 2 e mais 2 dias até o E-mail 3.

Os CTAs da sequência usam `utm_source=kit`, `utm_medium=email`, `utm_campaign=recovery_vigor360` e `utm_content=email_1|email_2|email_3`. A VSL preserva essas UTMs até a Kiwify, e `/kiwify` as persiste nos campos `checkout_utm_*`, permitindo atribuição de vendas ao e-mail clicado.

O fluxo de compra continua responsável por aplicar `Comprador Vigor 360`, que deve remover o contato da sequência no Kit antes do próximo e-mail. A interrupção E2E após `paid` ainda está pendente de validação final.

`journey_events` permanece telemetria e não participa da execução operacional da recuperação. Token assinado e `journey_run_id` na URL da VSL permanecem como hardening futuro.

## Recuperação de PIX gerado e não pago

O contrato real da Kiwify foi capturado em produção em 19/08/2026. Um PIX gerado chega em `POST /kiwify` com as condições simultâneas:

- `webhook_event_type = pix_created`;
- `order_status = waiting_payment`;
- `payment_method = pix`;
- `order_id` presente e estável.

A recuperação PIX é isolada da lógica existente de abandono e compra. O wrapper executa o `/kiwify` original exatamente uma vez e agenda separadamente os efeitos adicionais de PIX; falha na camada PIX não pode alterar a resposta do webhook principal.

Antes de qualquer RPC do ledger ou alteração de tag PIX, o worker confirma a venda server-to-server em `GET https://public-api.kiwify.com/v1/sales/{order_id}`. A autenticação oficial usa OAuth obtido com `KIWIFY_API_CLIENT_ID` e `KIWIFY_API_CLIENT_SECRET`, reutilizado em memória conforme `expires_in`, e `KIWIFY_ACCOUNT_ID` no header `x-kiwify-account-id`. Não há segredo em query string e o parâmetro `signature` do webhook não é usado sem especificação pública para validá-lo.

Para `pix_created`, a API deve devolver o mesmo `id`, `payment_method=pix` e status `pending` ou `waiting_payment`. Para pagamento, deve devolver o mesmo `id` e `status=paid`. O email usado no efeito Kit vem da resposta oficial. Credencial ausente, erro HTTP, rate limit, timeout, JSON inválido ou divergência de identidade/status/método falham fechados antes de subscribe, unsubscribe ou transição do ledger PIX.

### Inbox durável do webhook PIX

O HTTP 200 do webhook significa somente que o evento foi aceito e persistido; não significa que Kit e ledger já terminaram. Para `pix_created` e `paid`, o wrapper classifica o payload, grava sincronamente um job mínimo em `recovery_pix_jobs` e somente então executa o `/kiwify` legado exatamente uma vez e responde. Se o enqueue não for confirmado, a rota responde 503, permitindo reentrega pela Kiwify. A tabela guarda apenas `order_id`, tipo, estado, timestamps, tentativas e token de fencing; não guarda payload, email, CPF, IP, código PIX ou QR Code.

`(order_id, event_type)` é a chave primária da inbox. Duplicatas convergem para o mesmo job. A aquisição `recovery_pix_job_acquire` é um CAS atômico: somente `pending`, `retryable` ou `processing` stale pode receber um novo `attempt_token`. Conclusão/falha exigem o token atual, portanto worker antigo não finaliza uma tentativa nova. Falha de Kiwify, Supabase ou Kit volta o job para `retryable`; processo morto em `processing` pode ser readquirido depois de cinco minutos.

`BackgroundTasks` é apenas uma otimização de baixa latência depois da persistência. A garantia de entrega é a inbox no PostgreSQL. O endpoint autenticado `POST /internal/recovery-pix/reconcile`, com `Authorization: Bearer <PIX_RECOVERY_WORKER_TOKEN>`, deve ser chamado periodicamente por scheduler/cron independente do webhook. Ele busca jobs pendentes, retryable e processing, mas cada candidato ainda precisa vencer o CAS no PostgreSQL. Isso fornece retry e crash recovery mesmo após restart imediatamente posterior ao ACK.

`recovery_pix_orders` usa `order_id` como chave primária. Cada tentativa recebe um `attempt_token` único para fencing local. Em paralelo, `subscribe_attempted` registra de forma monotônica se **qualquer** tentativa daquela ordem já chegou a `processing -> subscribing`. Esse marcador não é substituído por retry stale e não volta para `false`.

Estados de trabalho são `processing`, `subscribing` e `failed`; `completed` é terminal para aquisição. Pagamentos usam `cancelled_pending_unsubscribe` e `cancelled`. A diferença agora é deliberadamente conservadora: `cancelled` automático só é permitido quando `subscribe_attempted=false`. Se qualquer tentativa já iniciou subscribe, o pagamento pode remover a tag naquele instante, mas o ledger permanece `cancelled_pending_unsubscribe` para manter detectável a possibilidade de um efeito remoto tardio.

Essa regra surgiu após a quarta auditoria Codex reproduzir um cenário em que tentativa `OLD` ficou stale, tentativa `NEW` substituiu o token, pagamento confirmou unsubscribe e só depois o servidor remoto efetivou o subscribe antigo. O fencing protegia o banco, mas não o efeito externo. `subscribe_attempted` resolve essa lacuna preservando evidência independente do token atual: a ordem não pode ficar silenciosamente `cancelled` se já houve subscribe tentado.

`failed` pode ser readquirido e `processing/subscribing` stale podem ser retomados após 5 minutos. As transições continuam limitadas a `processing -> subscribing`, `subscribing -> completed` e `subscribing -> failed`, condicionadas ao token atual. A primeira marca `subscribe_attempted=true` atomicamente.

Pagamento persiste `cancelled_pending_unsubscribe` antes de chamar o Kit. Falha/timeout de unsubscribe mantém pending. Um novo `paid` ou `pix_created` pode repetir unsubscribe sem reativar recovery. Quando `subscribe_attempted=true`, um unsubscribe bem-sucedido não finaliza automaticamente o ledger; a finalização posterior deverá ser uma etapa explícita/reconciliada, não inferida de uma única chamada externa.

As RPCs `SECURITY DEFINER` revogam `EXECUTE` de `PUBLIC`, `anon` e `authenticated` e concedem somente a `service_role`. O `search_path` é fixado em `pg_catalog, public`.

A tag de entrada será própria do PIX (`TAG_PIX_ID` no Render, tag `pix-gerado-vigor360` no Kit). O ledger não persiste CPF, IP, `pix_code`, QR Code ou payload completo.

A instalação limpa do ledger usa `sql/005_create_recovery_pix_orders.sql`. `sql/006_upgrade_recovery_pix_orders.sql` converge versões anteriores, `sql/007_create_recovery_pix_jobs.sql` cria a inbox durável e `sql/008_harden_recovery_pix_permissions.sql` aplica RLS/permissões finais tanto em instalações novas quanto já migradas.

O E2E real Kiwify -> Render -> Supabase -> Kit foi aprovado em 21/08/2026, incluindo falha inicial, retry após restart/reconciliação, conclusão na terceira tentativa, aplicação e remoção da tag PIX, preservação da tag de comprador e fila final sem candidatos.

## Recuperacao durable de boleto - fase 1

O boleto usa o contrato estrito `billet_created` + `payment_method=boleto` +
`order_status=waiting_payment`. A inbox e o ledger PIX sao ampliados por
compatibilidade para aceitar o metodo boleto, preservando CAS, fencing, retries,
reconciler e as RPCs existentes. A tag de entrada e exclusiva
(`TAG_BOLETO_ID`) e recebe `first_name` no proprio POST de subscribe.

`boleto_expiry_date` e convertido de `DD/MM/YYYY` para `expires_at`, sem persistir
URL ou codigo de barras. Nesta fase o vencimento nao dispara nenhuma acao.
Confirmar o contrato Kiwify de boleto expirado e uma pendencia obrigatoria antes
de automatizar retirada da recuperacao.
