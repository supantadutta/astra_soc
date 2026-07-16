"""LLM provider adapters and honest connectivity tests.

A connectivity test performs a REAL network call to the provider's API using
the resolved secret. It NEVER reports success without a confirming response.
When no secret is configured it returns a truthful ``not_configured`` state.
The built-in ``simulated`` provider always reports healthy because it is
in-process.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from ...models.enums import HealthState, ProviderKind
from ..secrets import resolve_secret, secret_configured


@dataclass
class ProviderTestResult:
    state: str  # HealthState value
    latency_ms: int
    detail: str
    error: str | None = None
    models_seen: int | None = None

    @property
    def ok(self) -> bool:
        return self.state == HealthState.HEALTHY.value


# Health-check endpoints/headers per provider kind.
def _headers_for(kind: str, secret: str | None) -> dict[str, str]:
    if kind == ProviderKind.ANTHROPIC.value:
        return {"x-api-key": secret or "", "anthropic-version": "2023-06-01"}
    if kind == ProviderKind.AZURE_OPENAI.value:
        return {"api-key": secret or ""}
    if kind in (ProviderKind.OPENAI.value, ProviderKind.OPENAI_COMPATIBLE.value,
                ProviderKind.VLLM.value, ProviderKind.GEMINI.value):
        return {"Authorization": f"Bearer {secret}"} if secret else {}
    return {"Authorization": f"Bearer {secret}"} if secret else {}


def _probe_url(kind: str, base_url: str | None) -> str | None:
    base = (base_url or _default_base(kind) or "").rstrip("/")
    if not base:
        return None
    if kind == ProviderKind.ANTHROPIC.value:
        return f"{base}/v1/models"
    if kind == ProviderKind.OLLAMA.value:
        return f"{base}/api/tags"
    if kind == ProviderKind.AZURE_OPENAI.value:
        return f"{base}/openai/models?api-version=2024-02-01"
    # OpenAI-compatible default.
    return f"{base}/v1/models" if not base.endswith("/v1") else f"{base}/models"


def _default_base(kind: str) -> str | None:
    return {
        ProviderKind.OPENAI.value: "https://api.openai.com",
        ProviderKind.ANTHROPIC.value: "https://api.anthropic.com",
        ProviderKind.OLLAMA.value: "http://localhost:11434",
    }.get(kind)


def test_connectivity(
    kind: str,
    base_url: str | None,
    secret_ref: str | None,
    timeout: int = 10,
) -> ProviderTestResult:
    """Actually connect to the provider and report the truthful result."""
    if kind == ProviderKind.SIMULATED.value:
        return ProviderTestResult(HealthState.HEALTHY.value, 1,
                                  "Built-in simulated provider (in-process).")

    # Ollama/vLLM may not need a secret; hosted providers do.
    needs_secret = kind not in (ProviderKind.OLLAMA.value, ProviderKind.VLLM.value)
    if needs_secret and not secret_configured(secret_ref):
        return ProviderTestResult(
            HealthState.NOT_CONFIGURED.value, 0,
            "No credential configured. Set a secret reference before testing.",
            error="missing_secret",
        )

    url = _probe_url(kind, base_url)
    if url is None:
        return ProviderTestResult(
            HealthState.NOT_CONFIGURED.value, 0,
            "No base URL configured for this provider.", error="missing_base_url",
        )

    secret = resolve_secret(secret_ref)
    headers = _headers_for(kind, secret)
    start = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
        latency = int((time.perf_counter() - start) * 1000)
        if resp.status_code in (200, 201):
            models_seen = _count_models(resp)
            return ProviderTestResult(
                HealthState.HEALTHY.value, latency,
                f"Connected. {models_seen if models_seen is not None else '?'} model(s) visible.",
                models_seen=models_seen,
            )
        if resp.status_code in (401, 403):
            return ProviderTestResult(
                HealthState.UNHEALTHY.value, latency,
                "Authentication rejected by provider.", error=f"http_{resp.status_code}")
        return ProviderTestResult(
            HealthState.DEGRADED.value, latency,
            f"Unexpected status {resp.status_code}.", error=f"http_{resp.status_code}")
    except httpx.ConnectError as exc:
        return ProviderTestResult(HealthState.UNHEALTHY.value, 0,
                                  "Could not connect to provider.", error=str(exc)[:200])
    except httpx.TimeoutException:
        return ProviderTestResult(HealthState.UNHEALTHY.value, timeout * 1000,
                                  "Provider timed out.", error="timeout")
    except Exception as exc:  # pragma: no cover
        return ProviderTestResult(HealthState.UNHEALTHY.value, 0,
                                  "Connectivity test failed.", error=str(exc)[:200])


def _count_models(resp: httpx.Response) -> int | None:
    try:
        data = resp.json()
    except Exception:
        return None
    if isinstance(data, dict):
        for key in ("data", "models"):
            if isinstance(data.get(key), list):
                return len(data[key])
    if isinstance(data, list):
        return len(data)
    return None


def chat_completion(
    kind: str,
    base_url: str | None,
    secret_ref: str | None,
    model: str,
    system: str,
    user: str,
    timeout: int = 60,
) -> tuple[str, dict]:
    """Call a real provider for a completion. Raises on failure so the gateway
    can fail over. Returns (text, usage)."""
    secret = resolve_secret(secret_ref)
    base = (base_url or _default_base(kind) or "").rstrip("/")
    if kind == ProviderKind.ANTHROPIC.value:
        url = f"{base}/v1/messages"
        payload = {"model": model, "max_tokens": 1500, "system": system,
                   "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": secret or "", "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", []))
        return text, data.get("usage", {})

    # OpenAI-compatible (OpenAI, Azure, vLLM, Ollama /v1, generic).
    if kind == ProviderKind.OLLAMA.value:
        url = f"{base}/v1/chat/completions"
    elif base.endswith("/v1"):
        url = f"{base}/chat/completions"
    else:
        url = f"{base}/v1/chat/completions"
    payload = {"model": model, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": user}]}
    headers = _headers_for(kind, secret) | {"content-type": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return text, data.get("usage", {})
