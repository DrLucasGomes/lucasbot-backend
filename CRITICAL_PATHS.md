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

- `/kiwify` original deve ser executado uma única vez e antes da camada adicional PIX;
- JSON inválido deve preservar o comportamento da rota original;
- `order_id` é a identidade operacional da recuperação PIX;
- `cancelled` é terminal e deve existir mesmo se `paid` chegar antes de `pix_created`;
- nunca readquirir `cancelled` ou `completed`;
- transições para `completed/failed` devem ser compare-and-set e jamais sobrescrever `cancelled`;
- antes do subscribe, exigir `processing -> subscribing` atômico;
- se o subscribe ocorrer e `paid` vencer a corrida, executar `unsubscribe` compensatório;
- `failed` pode ser retomado e `processing/subscribing` stale podem ser readquiridos após lease de 5 minutos;
- persistir o cancelamento antes de tentar `unsubscribe` no Kit;
- falha da camada PIX não pode impedir o processamento normal de compra/abandono no `/kiwify`;
- não persistir nem logar CPF, IP, `pix_code` ou dados de pagamento desnecessários;
- não reutilizar `TAG_ABANDONO_ID`; PIX usa `TAG_PIX_ID` próprio.

Antes do merge da recuperação PIX, exigir testes para: contrato válido, método/status/evento incorretos, `order_id` ausente, duplicata, concorrência entre dois PIX, `paid` antes do PIX, `paid` durante o subscribe, `paid` depois do PIX, falha do Kit, falha de transição, recuperação stale, JSON inválido e regressão de `cart_abandoned`/`paid` normal. A migration `005_create_recovery_pix_orders.sql`, o ID da tag no Render e um teste E2E real no Supabase/Kit são obrigatórios antes de produção.
