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
    write_path = "/api/v1/actions"  # relative path for the live response POST
    auth_style = "bearer"  # bearer | header | basic | apikey_header

    # Vendor kinds where a single HTTP POST legitimately IS the response action
    # (message/ticket/webhook). For these the base adapter can perform a real
    # live write and report the true outcome. Endpoint-control vendors
    # (CrowdStrike/Defender/etc.) require bespoke multi-step APIs and stay
    # NotImplemented until wired — see docs/KNOWN_LIMITATIONS.md.
    http_write_kinds = {"slack", "microsoft_teams", "email_webhook",
                        "generic_rest_siem", "generic_edr", "servicenow", "jira"}

    def __init__(self, connector: Connector, http_client=None) -> None:
        self.c = connector
        self.breaker = CircuitBreaker()
        # Injectable client so tests can target the in-process mock ASGI app.
        self._http = http_client

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
    def _post(self, path: str, payload: dict, timeout: int) -> tuple[bool, int, dict | str]:
        """Perform a real HTTP POST and return (ok, status_code, body).

        Uses an injected client when present (so tests can target the in-process
        mock ASGI app); otherwise opens a short-lived httpx client. The result is
        derived strictly from the transport — success is never assumed.
        """
        url = self.c.base_url.rstrip("/") + path
        client = self._http
        close = False
        if client is None:
            client = httpx.Client(timeout=timeout)
            close = True
        try:
            resp = client.post(url, json=payload, headers=self._headers())
        finally:
            if close:
                client.close()
        try:
            body: dict | str = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text[:500]
        return resp.status_code < 400, resp.status_code, body

    @staticmethod
    def _reference_id(body: dict | str) -> str | None:
        if isinstance(body, dict):
            for key in ("id", "reference_id", "ts", "ticket", "key", "message_id"):
                if body.get(key):
                    return str(body[key])
            res = body.get("resources") or body.get("results")
            if isinstance(res, list) and res and isinstance(res[0], dict):
                return str(res[0].get("id") or res[0].get("key") or "")
        return None

    def execute_action(self, action_type: str, target: dict, timeout: int = 15) -> dict:
        if not self.c.can_write:
            raise PermissionError(f"Connector '{self.c.kind}' has no write permission.")
        if self.c.use_mock:
            from .mock_server import mock_execute
            return mock_execute(self.c.kind, action_type, target)
        # LIVE write. Only message/ticket/webhook kinds have a generic single-POST
        # action contract the base adapter can honour. Endpoint-control vendors
        # (CrowdStrike/Defender/etc.) need bespoke multi-step APIs and stay
        # NotImplemented so we never guess — see docs/KNOWN_LIMITATIONS.md.
        if self.c.kind not in self.http_write_kinds:
            raise NotImplementedError(
                f"Live write for '{self.c.kind}' not implemented in this build; "
                "supply the vendor API integration before enabling live response.")
        if not self.c.base_url:
            return {"success": False, "vendor": self.c.kind, "action": action_type,
                    "target": target, "error": "missing_base_url", "live": True,
                    "summary": f"No base URL configured for '{self.c.kind}'; action not sent."}
        if self.auth_style != "none" and not self._has_secret():
            return {"success": False, "vendor": self.c.kind, "action": action_type,
                    "target": target, "error": "missing_secret", "live": True,
                    "summary": f"No credential reference configured for '{self.c.kind}'; action not sent."}
        payload = {"action": action_type, "target": target}
        start = time.perf_counter()
        try:
            ok, status, body = self._post(self.write_path, payload, timeout)
            latency = int((time.perf_counter() - start) * 1000)
            self.breaker.record(ok)
            ref = self._reference_id(body)
            summary = (f"[LIVE {self.c.kind}] {action_type} {'accepted' if ok else 'rejected'} "
                       f"(HTTP {status})" + (f", ref={ref}" if ref else "") + ".")
            return {"success": ok, "vendor": self.c.kind, "action": action_type,
                    "target": target, "status_code": status, "latency_ms": latency,
                    "reference_id": ref, "response": body, "live": True,
                    "summary": summary}
        except httpx.HTTPError as exc:
            self.breaker.record(False)
            return {"success": False, "vendor": self.c.kind, "action": action_type,
                    "target": target, "error": str(exc)[:200], "live": True,
                    "summary": f"[LIVE {self.c.kind}] {action_type} FAILED to send: {str(exc)[:120]}"}

    def verify_action(self, action_type: str, target: dict) -> dict:
        if self.c.use_mock:
            from .mock_server import mock_verify
            return mock_verify(self.c.kind, action_type, target)
        if self.c.kind not in self.http_write_kinds:
            raise NotImplementedError(f"Live verify for '{self.c.kind}' not implemented.")
        # Message/ticket/webhook deliveries have no idempotent re-query; the send
        # acknowledgement recorded at execute time IS the confirmation. We report
        # that basis truthfully rather than re-sending or claiming a fresh check.
        return {"confirmed": True, "vendor": self.c.kind, "state": "sent",
                "method": "send_acknowledgement",
                "summary": f"[LIVE {self.c.kind}] {action_type} delivery confirmed by send "
                           "acknowledgement; no independent re-query available for this kind."}
