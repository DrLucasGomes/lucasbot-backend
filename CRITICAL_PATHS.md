# Caminhos críticos

## Escopo

São pontos críticos os fluxos de `/webhook`, `/kiwify`, tracking, persistência em `leads_vigor`, atribuição por `click_sessions` e instrumentação de `journey_events`.

`journey_events` é telemetria best-effort. Uma falha ao registrar evento não pode impedir o avanço do usuário, a atualização do lead, o processamento de compra ou a atribuição de tracking. Correções de telemetria não devem mudar contratos dos fluxos principais.

## Procedimento seguro de mudança

Antes de alterar um ponto crítico:

1. Crie uma branch dedicada.
2. Rode `pytest` e confirme a linha de base.
3. Faça a mudança com o menor escopo possível.
4. Peça uma auditoria adversarial no VS Code/Codex antes do merge, com perguntas explícitas sobre regressão, concorrência, ordenação, idempotência, retry e exposição de dados.
5. Corrija os riscos encontrados e rode novamente toda a suíte.
6. Revise o diff, incluindo migrations e contratos HTTP.
7. Atualize `ARCHITECTURE.md`, `CRITICAL_PATHS.md` e ADRs quando houver decisão estrutural.
8. Abra um PR com riscos e evidências de teste.
9. Aguarde a CI verde antes do merge.

Para mudanças em jornada, confirme especialmente a preservação de `manychat_id`, `journey_run_id` e `dedupe_key`, o comportamento best-effort e a ausência de updates ou deletes em `journey_events`.

## Runtime de produção

Produção não deve ser movida de volta para o Render Free sem reavaliar explicitamente o risco de spin-down e cold start. Essa avaliação deve considerar a latência da primeira requisição e possíveis timeouts ou atrasos nos fluxos do ManyChat, da Kiwify e de `journey_events`.

## Recuperação pós-play da VSL

O primeiro play elegível da VSL e o abandono de checkout são gatilhos distintos. Não misture `POST /recovery/video-play` com `cart_abandoned` nem altere o fluxo de recuperação de checkout ao evoluir a recuperação pós-play.

Regras críticas:

- nunca confiar em e-mail enviado pelo navegador; a identidade V1 é somente `src=mc_<manychat_id>` e o e-mail vem de `leads_vigor`;
- não remover a proteção de `STATUS_PAGOS`: comprador é inelegível para a tag de recuperação pós-play;
- manter a migration `004_create_recovery_video_plays.sql` no Supabase;
- manter `TAG_RECUPERACAO_VIDEO_ID` no Render com o ID da tag `recuperacao-pos-clique-vigor360`;
- manter falhas de Supabase ou Kit fora do caminho crítico do player: a recuperação nunca pode impedir o vídeo de tocar;
- preservar no player `enablejsapi=1`, o ID usado pela integração e o comportamento atual do vídeo;
- preservar o botão `.botao-vigor` e o repasse de `src` e UTMs para a Kiwify;
- não trocar `utm_content=email_1|email_2|email_3` por `src`: `utm_content` identifica o e-mail e `src` mantém sua função de identidade/origem;
- preservar a cadência do Kit: +1h E-mail 1, +1 dia E-mail 2, +2 dias E-mail 3;
- `paid` deve retirar o contato da recuperação antes do próximo e-mail.

A tabela `recovery_video_plays` protege concorrência e retries por estado. Não remova a terminalidade de `completed`, o retry de `failed` nem a recuperação de `processing` stale após 5 minutos sem reavaliar a idempotência do fluxo.

## Testes E2E obrigatórios da recuperação

Antes de considerar mudanças futuras prontas, validar:

1. acesso elegível sem PLAY não dispara recuperação;
2. primeiro PLAY cria/processa uma única recuperação até `completed`;
3. pausa/PLAY repetido não duplica;
4. acesso sem `src=mc_...` não dispara;
5. tag `recuperacao-pos-clique-vigor360` é aplicada e o contato entra na sequência correta do Kit;
6. CTA de cada e-mail preserva `utm_content=email_N` até a Kiwify;
7. `/kiwify` persiste `checkout_utm_content=email_N` no Supabase;
8. após o E-mail 1, um `paid` remove o contato da recuperação e impede E-mails 2 e 3.

Os itens 1 a 7 foram validados para a implementação atual, incluindo atribuição sintética do E-mail 1. O item 8 está em validação final com a cadência real da sequência.

## Recuperação PIX

PIX gerado, abandono de checkout e play da VSL são gatilhos diferentes e devem permanecer isolados.

Contrato operacional confirmado da Kiwify para entrada PIX:

- `webhook_event_type = pix_created`;
- `order_status = waiting_payment`;
- `payment_method = pix`;
- `order_id` obrigatório.

Invariantes que não podem ser quebradas:

- `/kiwify` original deve ser executado exatamente uma vez; a camada adicional PIX roda isoladamente em background;
- antes de qualquer efeito PIX, confirmar a venda em `GET /v1/sales/{order_id}` com OAuth oficial da Kiwify;
- `pix_created` exige identidade exata, método PIX e status oficial `pending`/`waiting_payment`; `paid` exige identidade exata e status oficial `paid`;
- qualquer falha de credencial, HTTP, timeout, JSON ou divergência deve falhar fechada sem RPC/transição/tag PIX;
- credenciais Kiwify são `KIWIFY_API_CLIENT_ID`, `KIWIFY_API_CLIENT_SECRET` e `KIWIFY_ACCOUNT_ID`; nunca entram em URL, logs ou payload persistido;
- ACK do webhook não significa efeito concluído: `pix_created`/`paid` devem estar na inbox `recovery_pix_jobs` antes do HTTP 200;
- falha ao persistir inbox deve produzir resposta não-2xx; nunca confirmar recebimento sem cópia durável;
- `(order_id, event_type)` impede duplicação lógica e o job contém somente identidade mínima, estado, tentativas, fencing e timestamps;
- `BackgroundTasks` é somente otimização pós-enqueue, nunca garantia de entrega;
- aquisição/conclusão/falha do job exigem CAS e `attempt_token`; `processing` stale deve ser recuperável;
- `POST /internal/recovery-pix/reconcile` exige `PIX_RECOVERY_WORKER_TOKEN` e chamada periódica externa ao webhook;
- falhas externas mantêm o job `retryable`; crash depois do ACK é retomado pela reconciliação;
- JSON inválido deve preservar o comportamento da rota original;
- `order_id` é a identidade operacional da recuperação PIX;
- cada tentativa usa `attempt_token` único como fencing token para CAS local;
- `subscribe_attempted` é monotônico: uma vez `true`, nunca volta para `false`, inclusive após retry stale com token novo;
- `processing -> subscribing` deve marcar `subscribe_attempted=true` atomicamente;
- pagamento persiste `cancelled_pending_unsubscribe` antes de chamar o Kit;
- se `subscribe_attempted=false`, unsubscribe confirmado pode permitir `cancelled`;
- se `subscribe_attempted=true`, **não confirmar `cancelled` automaticamente**, mesmo após unsubscribe bem-sucedido; manter pending detectável para que efeito remoto tardio de qualquer tentativa antiga nunca fique escondido;
- `cancelled_pending_unsubscribe`, `cancelled` e `completed` não podem ser readquiridos para subscribe;
- stale retry troca `attempt_token`, mas nunca apaga o histórico monotônico de que houve subscribe tentado;
- worker antigo não pode concluir/falhar tentativa nova; se seu token já perdeu autoridade, a segurança contra efeito remoto tardio vem de `subscribe_attempted`, não de reabrir o token atual;
- `recovery_pix_reopen_cancel` exige token correspondente e `subscribe_attempted=true`;
- as únicas transições normais são `processing -> subscribing`, `subscribing -> completed` e `subscribing -> failed`;
- falha/timeout de unsubscribe mantém pending;
- nova entrega de `paid` ou `pix_created` pode repetir reconciliação pending sem reativar recovery;
- falha da camada PIX não pode impedir compra/abandono no `/kiwify`;
- não persistir/logar CPF, IP, `pix_code`, QR Code ou payload de pagamento;
- PIX usa `TAG_PIX_ID` próprio, nunca `TAG_ABANDONO_ID`;
- boleto usa `TAG_BOLETO_ID` proprio e nunca pode remover `TAG_PIX_ID`;
- boleto exige exatamente `billet_created`, `payment_method=boleto` e
  `order_status=waiting_payment`;
- `expires_at` de boleto e apenas informativo na fase 1: nao criar timer, sleep
  ou cancelamento por relogio sem confirmar o contrato de expiracao da Kiwify;
- RPCs `SECURITY DEFINER` são restritas a `service_role`;
- instalação limpa do ledger usa `005_create_recovery_pix_orders.sql`; upgrade defensivo usa `006_upgrade_recovery_pix_orders.sql`; a inbox durável usa `007_create_recovery_pix_jobs.sql`; permissões finais convergem por `008_harden_recovery_pix_permissions.sql`.

Antes do merge, testar explicitamente o cenário adversarial: tentativa OLD chega a `subscribing`, fica stale, tentativa NEW substitui token, `paid` executa unsubscribe e depois o subscribe remoto OLD é efetivado. O estado local **não pode estar `cancelled`** nesse cenário; deve permanecer `cancelled_pending_unsubscribe` porque `subscribe_attempted=true`. Também são obrigatórios testes de concorrência real/RPCs no Supabase, permissões, JSON inválido, regressão de `cart_abandoned`/`paid`, tag do Kit e E2E Kiwify -> Render -> Supabase -> Kit.
