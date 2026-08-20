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

A recuperação PIX é isolada da lógica existente de abandono e compra. O wrapper executa primeiro o `/kiwify` original e somente depois agenda efeitos adicionais de PIX; falha na camada PIX não pode alterar a resposta do webhook principal.

`recovery_pix_orders` usa `order_id` como chave primária. Cada tentativa de trabalho recebe também um `attempt_token` único, usado como fencing token. Aquisição stale substitui o token; portanto um worker antigo não consegue concluir, falhar ou reabrir o cancelamento de uma tentativa nova.

Estados de trabalho são `processing`, `subscribing` e `failed`; `completed` é terminal para aquisição. Pagamentos usam dois estados de cancelamento: `cancelled_pending_unsubscribe` bloqueia imediatamente qualquer nova aquisição e registra que a remoção remota ainda precisa ser confirmada; `cancelled` significa que um unsubscribe foi confirmado depois do último subscribe conhecido.

`failed` pode ser readquirido e `processing/subscribing` stale podem ser retomados após 5 minutos. As únicas transições comuns permitidas são `processing -> subscribing`, `subscribing -> completed` e `subscribing -> failed`, sempre condicionadas ao `attempt_token` atual.

Pagamento confirmado persiste primeiro `cancelled_pending_unsubscribe` por `order_id`, mesmo que `pix_created` ainda não tenha chegado. O unsubscribe acontece depois. Se falhar ou houver timeout, o estado pending permanece durável e uma nova entrega de `paid` ou `pix_created` pode tentar reconciliar novamente sem reativar a recuperação. Só depois de unsubscribe confirmado o ledger passa para `cancelled`.

Uma auditoria adversarial encontrou uma corrida adicional: um `subscribe` antigo podia ser efetivado pelo Kit depois de um `unsubscribe` já confirmado, deixando ledger `cancelled` com tag presente. Para impedir estado silenciosamente divergente, o worker que realmente tentou `subscribe` e perde o CAS para `completed` usa seu `attempt_token` para executar `cancelled -> cancelled_pending_unsubscribe` antes da compensação. Assim um subscribe tardio conhecido sempre produz novo unsubscribe posterior.

Se o resultado do `subscribe` for ambíguo por timeout/exceção, a compensação não confirma `cancelled` imediatamente. Mesmo que um unsubscribe retorne sucesso, o ledger permanece `cancelled_pending_unsubscribe`, porque o servidor remoto ainda pode concluir o subscribe depois do timeout local. Isso mantém a divergência potencial detectável e exige uma reconciliação futura antes do estado terminal.

As RPCs `SECURITY DEFINER` revogam `EXECUTE` de `PUBLIC`, `anon` e `authenticated` e concedem execução somente a `service_role`. O `search_path` é fixado em `pg_catalog, public` e objetos persistentes são qualificados.

A tag de entrada será própria do PIX (`TAG_PIX_ID` no Render, tag `pix-gerado-vigor360` no Kit). O ledger não persiste CPF, IP, `pix_code`, QR Code ou payload completo.

A instalação limpa usa `sql/005_create_recovery_pix_orders.sql`. Existe também `sql/006_upgrade_recovery_pix_orders.sql`, idempotente, para convergir qualquer ambiente onde uma versão anterior da 005 tenha sido aplicada; a 006 também adiciona `attempt_token` e remove assinaturas antigas das RPCs antes de criar as versões cercadas pelo fencing token.

A feature permanece em branch de teste até auditoria Codex final, suíte completa, execução das migrations no Supabase, criação/configuração da tag e teste E2E real Kiwify -> Render -> Supabase -> Kit serem aprovados.
