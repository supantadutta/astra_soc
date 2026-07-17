# Demo Mode

Demo mode is a **backend-enforced operating state** (stored in `SystemSetting`,
key `operating_mode`), not a frontend toggle.

- Requires no external credentials; seeds 15 attack scenarios and a full RBAC
  matrix, simulated LLM provider, agents, tools, connectors, detections,
  playbooks and response policy on first boot.
- A background generator produces synthetic OCSF-style events continuously; the
  UI updates via SSE. Control it in **Demo Control Center** (pause / speed /
  reset / launch scenario).
- All AI runs use the deterministic **simulated reasoner** unless you configure a
  real provider. Every simulated result is labelled `SIMULATED`.
- Response actions are **always simulated** in demo — no production command is
  ever sent — and the response gateway records `simulated: true`.
- All demo data carries `data_scope="DEMO"`. Queries filter by scope, so demo and
  live data never mix.

**Reset:** `make demo-reset`, the Demo Control Center button, or
`POST /api/v1/demo/reset`. Only DEMO-scoped rows are deleted; LIVE data is
untouched.

## Six operating combinations
1. Demo data + simulated LLM (default)
2. Demo data + real LLM (add a provider; tools stay simulated)
3. Live data + local private LLM (vLLM/Ollama, `private_only`)
4. Live data + hosted LLMs
5. Live data + hybrid routing (sensitivity-aware)
6. Live data + AI disabled (deterministic pipeline only)
