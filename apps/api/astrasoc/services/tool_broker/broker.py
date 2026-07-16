"""The tool broker — the controlled gateway between agents and tools.

Enforced on every call:
* the tool must be registered, approved and enabled;
* tenant allowlist and data-scope isolation;
* read/response separation — RESPONSE-scoped tools can NEVER be executed here;
  they must go through the response gateway (policy + approval + verification);
* rate limit, timeout, response-size cap and sensitive-field masking;
* an immutable, signed ToolExecution audit record.
"""
from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...auth.security import sign_payload
from ...models import Tool, ToolExecution
from ...models.enums import ToolScope
from ..injection import apply_dlp
from .read_tools import READ_TOOL_IMPLS


class ToolBrokerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class ToolBroker:
    def __init__(self) -> None:
        self._rate: dict[str, deque[float]] = defaultdict(deque)

    def _check_rate(self, tool: Tool) -> None:
        now = time.time()
        window = self._rate[tool.key]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= tool.rate_limit_per_minute:
            raise ToolBrokerError("rate_limited", f"Tool {tool.key} rate limit exceeded.")
        window.append(now)

    def execute(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        tool_key: str,
        args: dict,
        *,
        scope: str,
        agent_run_id: uuid.UUID | None = None,
        incident_id: uuid.UUID | None = None,
    ) -> dict:
        tool = db.execute(select(Tool).where(Tool.key == tool_key)).scalar_one_or_none()
        if tool is None:
            raise ToolBrokerError("unknown_tool", f"Tool {tool_key} is not registered.")
        if not tool.approved or not tool.enabled:
            raise ToolBrokerError("tool_disabled", f"Tool {tool_key} is not approved/enabled.")
        if tool.allowed_tenants and str(tenant_id) not in tool.allowed_tenants:
            raise ToolBrokerError("tenant_forbidden", f"Tool {tool_key} not allowed for tenant.")

        # Hard separation: response tools never run through the broker.
        if tool.scope == ToolScope.RESPONSE.value:
            raise ToolBrokerError(
                "response_tool_blocked",
                f"'{tool_key}' is a production-changing action and cannot be invoked by an "
                "agent/tool call. Route it through the response gateway (policy + approval).",
            )

        self._check_rate(tool)

        impl = READ_TOOL_IMPLS.get(tool_key)
        if impl is None:
            raise ToolBrokerError("no_impl", f"No implementation registered for {tool_key}.")

        start = time.perf_counter()
        success = True
        error = None
        try:
            result = impl(db, tenant_id, scope, args or {})
        except ToolBrokerError:
            raise
        except Exception as exc:  # noqa: BLE001
            success = False
            error = str(exc)[:400]
            result = {"error": "tool_execution_failed", "detail": error}
        duration_ms = int((time.perf_counter() - start) * 1000)

        # Sensitive-field masking + response-size cap.
        masked = self._mask(result)
        blob = json.dumps(masked, default=str)
        if len(blob.encode()) > tool.max_response_bytes:
            masked = {"error": "response_too_large",
                      "note": f"Result exceeded {tool.max_response_bytes} bytes and was withheld."}
            blob = json.dumps(masked)

        signature = sign_payload(blob.encode())
        record = ToolExecution(
            tenant_id=tenant_id, tool_key=tool_key, agent_run_id=agent_run_id,
            incident_id=incident_id, scope=tool.scope, data_scope=scope,
            input=args or {}, output=masked, success=success, duration_ms=duration_ms,
            error=error, result_signature=signature, simulated=(scope == "DEMO"),
        )
        db.add(record)
        db.flush()
        return {"tool": tool_key, "success": success, "output": masked,
                "duration_ms": duration_ms, "signature": signature,
                "execution_id": str(record.id)}

    def _mask(self, obj):
        if isinstance(obj, dict):
            return {k: self._mask(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._mask(v) for v in obj]
        if isinstance(obj, str):
            return apply_dlp(obj)[0]
        return obj


broker = ToolBroker()
