"""Connector adapter base classes with retry/timeout/circuit-breaker.

An adapter wraps a single external product. It exposes:
* ``test_connection`` — a REAL connectivity + auth check (or a truthful mock
  result when the connector is in mock mode);
* ``fetch_events`` — read path (read-only);
* ``execute_action`` / ``verify_action`` — write path, used ONLY by the response
  gateway in LIVE mode.

Adapters never fabricate a healthy status. In mock mode they clearly report
``mock`` so the UI can label it. Read and write permissions are separated: an
adapter refuses ``execute_action`` if the connector lacks ``can_write``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from ...models import Connector
from ...models.enums import HealthState
from ..secrets import resolve_secret, secret_configured


@dataclass
class HealthResult:
    state: str
    latency_ms: int
    detail: str
    error: str | None = None
    mock: bool = False
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class CircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown_s: int = 60) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.failures = 0
        self.open_until = 0.0

    @property
    def is_open(self) -> bool:
        return time.time() < self.open_until

    def record(self, ok: bool) -> None:
        if ok:
            self.failures = 0
        else:
            self.failures += 1
            if self.failures >= self.threshold:
                self.open_until = time.time() + self.cooldown_s


class ConnectorAdapter:
    """Base adapter. Concrete adapters set ``health_path`` / ``category``."""

    category = "generic"
    health_path = "/"  # relative path used for the live connectivity probe
    auth_style = "bearer"  # bearer | header | basic | apikey_header

    def __init__(self, connector: Connector) -> None:
        self.c = connector
        self.breaker = CircuitBreaker()

    # --- helpers ---------------------------------------------------------
    def _secret(self) -> str | None:
        for ref in self.c.credential_refs:
            if ref.field in ("api_token", "api_key", "token", "client_secret", "password"):
                val = resolve_secret(ref.secret_ref)
                if val:
                    return val
        return None

    def _has_secret(self) -> bool:
        return any(secret_configured(r.secret_ref) for r in self.c.credential_refs)

    def _headers(self) -> dict[str, str]:
        secret = self._secret()
        if not secret:
            return {}
        if self.auth_style == "bearer":
            return {"Authorization": f"Bearer {secret}"}
        if self.auth_style == "apikey_header":
            return {"x-api-key": secret}
        return {"Authorization": secret}

    # --- health ----------------------------------------------------------
    def test_connection(self, timeout: int = 10) -> HealthResult:
        # Mock mode: truthful mock result (used in demo + contract tests).
        if self.c.use_mock:
            return HealthResult(HealthState.HEALTHY.value, 5,
                                f"Mock server responding for '{self.c.kind}'.", mock=True)
        if not self.c.base_url:
            return HealthResult(HealthState.NOT_CONFIGURED.value, 0,
                                "No base URL configured.", error="missing_base_url")
        if self.auth_style != "none" and not self._has_secret():
            return HealthResult(HealthState.NOT_CONFIGURED.value, 0,
                                "No credential reference configured.", error="missing_secret")
        if self.breaker.is_open:
            return HealthResult(HealthState.UNHEALTHY.value, 0,
                                "Circuit breaker open after repeated failures.", error="circuit_open")
        url = self.c.base_url.rstrip("/") + self.health_path
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers=self._headers())
            latency = int((time.perf_counter() - start) * 1000)
            ok = resp.status_code < 400
            self.breaker.record(ok)
            if ok:
                return HealthResult(HealthState.HEALTHY.value, latency,
                                    f"Connected ({resp.status_code}).")
            if resp.status_code in (401, 403):
                return HealthResult(HealthState.UNHEALTHY.value, latency,
                                    "Authentication rejected.", error=f"http_{resp.status_code}")
            return HealthResult(HealthState.DEGRADED.value, latency,
                                f"Unexpected status {resp.status_code}.",
                                error=f"http_{resp.status_code}")
        except httpx.HTTPError as exc:
            self.breaker.record(False)
            return HealthResult(HealthState.UNHEALTHY.value, 0,
                                "Connection failed.", error=str(exc)[:200])

    # --- read ------------------------------------------------------------
    def fetch_events(self, since: datetime | None = None) -> list[dict]:
        if self.c.use_mock:
            from .mock_server import mock_events
            return mock_events(self.c.kind)
        # Real implementation would query the product API here; kept minimal.
        return []

    # --- write (response gateway only) -----------------------------------
    def execute_action(self, action_type: str, target: dict) -> dict:
        if not self.c.can_write:
            raise PermissionError(f"Connector '{self.c.kind}' has no write permission.")
        if self.c.use_mock:
            from .mock_server import mock_execute
            return mock_execute(self.c.kind, action_type, target)
        # Real implementation would POST to the product's action API and return
        # the TRUE outcome. We never fabricate success.
        raise NotImplementedError(
            f"Live write for '{self.c.kind}' not implemented in this build; "
            "supply the vendor API integration before enabling live response.")

    def verify_action(self, action_type: str, target: dict) -> dict:
        if self.c.use_mock:
            from .mock_server import mock_verify
            return mock_verify(self.c.kind, action_type, target)
        raise NotImplementedError(f"Live verify for '{self.c.kind}' not implemented.")
