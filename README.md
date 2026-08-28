# lucasbot-backend

## Documentação do projeto

- [Arquitetura](ARCHITECTURE.md)
- [Caminhos críticos](CRITICAL_PATHS.md)
- [Tracking de QR para a VSL](docs/qr-vsl-tracking.md)

### Decisões arquiteturais

- [ADR-001: `journey_events` append-only](docs/decisions/ADR-001-journey-events-append-only.md)
- [ADR-002: `journey_run_id`](docs/decisions/ADR-002-journey-run-id.md)
- [ADR-003: Render Starter para evitar spin-down](docs/decisions/ADR-003-render-starter-no-spin-down.md)

### Antes de alterar produção

1. Leia a arquitetura.
2. Leia os caminhos críticos.
3. Consulte o ADR relacionado.
4. Crie uma branch dedicada.
5. Rode os testes e confirme a linha de base.
6. Implemente a alteração.
7. Revise o `git diff`.
8. Rode os testes novamente.
9. Abra um PR.
10. Aguarde a CI verde antes do merge.

Agentes e ferramentas de IA devem ler `ARCHITECTURE.md`, `CRITICAL_PATHS.md` e os ADRs relacionados antes de propor qualquer alteração estrutural.
