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

## Recuperação após o play da VSL

`POST /recovery/video-play` é o gatilho operacional do primeiro play elegível da VSL do Vigor 360. Esse fluxo é independente do clique no checkout e de `cart_abandoned`.

Na V1, o endpoint aceita identidade exclusivamente por `src=mc_<manychat_id>`. O e-mail não é aceito do navegador: ele é obtido de `leads_vigor`. Leads sem e-mail válido, inexistentes ou com `status_pagamento` em `STATUS_PAGOS` não recebem a tag `recuperacao-pos-clique-vigor360` no Kit.

A VSL está integrada à YouTube IFrame API e dispara o endpoint apenas no primeiro estado real `PLAYING` elegível. O endpoint aceita CORS dos hosts oficiais do site. Falha de tracking não interfere no player.

O estado operacional e a deduplicação ficam em `recovery_video_plays`, com uma linha única por `manychat_id`. `completed` é terminal, `failed` pode ser retomado e `processing` pode ser readquirido atomicamente quando estiver stale há mais de 5 minutos. A integração é at-least-once com deduplicação local, sem garantia de exactly-once entre Supabase e Kit.

A tag inicia no Kit a sequência `Vigor 360 — Recuperação Pós-Clique`, com cadência definitiva: 1 hora até o E-mail 1, mais 1 dia até o E-mail 2 e mais 2 dias até o E-mail 3.

Os CTAs da sequência usam `utm_source=kit`, `utm_medium=email`, `utm_campaign=recovery_vigor360` e `utm_content=email_1|email_2|email_3`. A VSL preserva essas UTMs até a Kiwify, e `/kiwify` as persiste nos campos `checkout_utm_*`, permitindo atribuição de vendas ao e-mail clicado.

O fluxo de compra continua responsável por aplicar `Comprador Vigor 360`, que deve remover o contato da sequência no Kit antes do próximo e-mail. A interrupção E2E após `paid` ainda está pendente de validação final.

`journey_events` permanece telemetria e não participa da execução operacional da recuperação. Token assinado e `journey_run_id` na URL da VSL permanecem como hardening futuro.
