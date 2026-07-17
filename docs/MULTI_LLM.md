# Multi-LLM Platform

## Providers
OpenAI, Azure OpenAI, Anthropic, Google Gemini, AWS Bedrock, local vLLM, local
Ollama, and any OpenAI-compatible endpoint. Plus a built-in **simulated**
provider for zero-dependency operation.

Configure in **AI Model Operations**. Each provider supports: enable/disable,
endpoint, model id, **secret reference** (never a plaintext key), connectivity
test, capability tags, data-classification allowance, region, cost, token/rate
limits, timeout, retry, circuit breaker, health, fallback priority, usage
metrics, error history.

## Connectivity tests are truthful
`POST /models/providers/{id}/test` performs a **real** HTTP call using the
resolved secret. With no secret it returns `not_configured`; on auth failure,
`unhealthy`. It never fakes a healthy status.

## Capability aliases
`fast_triage`, `deep_investigator`, `independent_critic`, `private_investigator`,
`detection_engineer`, `malware_analyst`, `multimodal_analyst`, `report_writer`,
`embedding_model`, `security_classifier`, `response_planner`.

## Routing
A `ModelRoute` maps a capability → primary / fallback / verifier / shadow
deployments. The gateway selects by capability, honoring circuit breakers,
budgets, and private-only tenant policy, then validates output against the
evidence-first schema. On failure it fails over: primary → fallback → simulated.

## Independent verification
High-risk capabilities require verification by a **different provider** or, if
none is available, a **deterministic validator** (checks the claim cites real
evidence and clears the confidence bar). Verification never silently no-ops.

## Budgets & failover
Per-tenant daily/monthly limits, per-provider circuit breakers, provider
failover, and private-model-only policies are all supported.
