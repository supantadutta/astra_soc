# Agents

Agent **definitions** (guardrails, tool allowlists, budgets) are seeded from
`apps/api/astrasoc/seed/catalog.py`; the **orchestrator and coordinator workflow
graph** live in `apps/api/astrasoc/services/agents/`. This directory is the
extension point for packaged agent prompt/versions.

See [../docs/AGENTS.md](../docs/AGENTS.md).
