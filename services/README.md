# Services

The logical services below are **implemented in-process inside `apps/api`** for
zero-dependency demo startup, each behind a clean module boundary that maps onto
a standalone deployable in production:

| Logical service | Implementation |
|-----------------|----------------|
| agent-orchestrator | `apps/api/astrasoc/services/agents/` |
| model-gateway | `apps/api/astrasoc/services/model_gateway/` |
| tool-broker | `apps/api/astrasoc/services/tool_broker/` |
| response-gateway | `apps/api/astrasoc/services/response.py` |
| event-normalizer | `apps/api/astrasoc/seed/engine.py` (OCSF mapping) + connectors |
| detection-engine | `apps/api/astrasoc/services/detection.py` |
| incident-fusion | correlation in `apps/api/astrasoc/routers/alerts.py` + engine |
| reporting | `apps/api/astrasoc/services/reporting.py` |

`connector-gateway/` is reserved for an optional high-throughput Go service that
speaks the same typed adapter contract.

See [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).
