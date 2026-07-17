# Packages

Shared building blocks. In this build they are co-located with the app that owns
them for simplicity; the boundaries are real and can be extracted to standalone
workspace packages:

- **ui** — the React design system: `apps/web/src/components/` + `src/styles/`.
- **schemas** — Pydantic + AI output contracts: `apps/api/astrasoc/schemas/`
  (mirror `packages/schemas/README.md`).
- **connector-sdk** — adapter base + registry: `apps/api/astrasoc/services/connectors/`.
- **agent-sdk** — agent orchestrator + registry: `apps/api/astrasoc/services/agents/`.
- **shared** — enums, config, db types: `apps/api/astrasoc/{config,db,models}`.
