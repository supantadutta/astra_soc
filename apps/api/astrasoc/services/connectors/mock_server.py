"""In-process mock server backing connectors in mock/demo mode, plus a
standalone FastAPI app usable for connector contract tests.

The standalone app (``mock_app``) implements minimal, realistic endpoints for a
few vendors so integration tests can exercise the real adapter HTTP path
without any external credentials. Run it with:

    uvicorn astrasoc.services.connectors.mock_server:mock_app --port 9900
"""
from __future__ import annotations

import random
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException


# --- In-process mock data (used when connector.use_mock is True) ----------
def mock_events(kind: str) -> list[dict]:
    now = datetime.now(UTC).isoformat()
    n = random.randint(1, 4)
    return [
        {"source": kind, "ts": now, "activity": random.choice(
            ["auth_success", "process_create", "network_connection", "file_write"]),
         "severity": random.choice(["low", "medium", "high"]), "mock": True}
        for _ in range(n)
    ]


def mock_execute(kind: str, action_type: str, target: dict) -> dict:
    return {
        "success": True, "vendor": kind, "action": action_type, "target": target,
        "reference_id": f"mock-{random.randint(10000, 99999)}",
        "summary": f"[MOCK {kind}] {action_type} acknowledged for {target}.",
    }


def mock_verify(kind: str, action_type: str, target: dict) -> dict:
    return {"confirmed": True, "vendor": kind, "state": "applied",
            "summary": f"[MOCK {kind}] verified {action_type} on {target}."}


# --- Standalone mock HTTP server (for adapter contract tests) -------------
mock_app = FastAPI(title="ASTRASOC Mock Integration Server", version="1.0.0")

_VALID_TOKEN = "mock-valid-token"


def _auth(authorization: str | None, x_api_key: str | None) -> None:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    token = token or x_api_key
    if token != _VALID_TOKEN:
        raise HTTPException(status_code=401, detail="invalid credentials")


@mock_app.get("/health")
def health():
    return {"status": "ok", "server": "astrasoc-mock"}


@mock_app.get("/services/collection/jobs/export")  # Splunk-ish
@mock_app.get("/api/v1/events")                     # generic REST SIEM
def events(authorization: str | None = Header(None), x_api_key: str | None = Header(None)):
    _auth(authorization, x_api_key)
    return {"results": mock_events("mock")}


@mock_app.post("/devices/entities/devices-actions/v2")  # CrowdStrike-ish isolate
@mock_app.post("/api/v1/actions")
def action(payload: dict, authorization: str | None = Header(None),
           x_api_key: str | None = Header(None)):
    _auth(authorization, x_api_key)
    return {"resources": [{"id": f"mock-{random.randint(1000,9999)}", "status": "accepted"}]}
