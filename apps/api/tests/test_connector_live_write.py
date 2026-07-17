"""Live-mode connector write path reports the TRUE HTTP outcome.

These tests exercise the real adapter HTTP code path (not the mock branch) by
pointing an injected httpx client at the in-process mock integration ASGI app.
The point is honesty: a 2xx yields success=True, a 401 yields success=False —
the adapter never fabricates a healthy result.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from astrasoc.models import Connector, ConnectorCredentialReference
from astrasoc.services.connectors.mock_server import mock_app
from astrasoc.services.connectors.registry import get_adapter


def _live_slack_connector(secret_ref: str, can_write: bool = True) -> Connector:
    c = Connector(
        name="Slack (live-path test)", kind="slack", category="comms",
        enabled=True, base_url="http://mock-slack", use_mock=False,
        can_read=True, can_write=can_write,
    )
    c.credential_refs = [
        ConnectorCredentialReference(field="api_token", secret_ref=secret_ref)
    ]
    return c


@pytest.fixture
def asgi_client():
    # Starlette's TestClient is a *synchronous* httpx.Client bound to the ASGI
    # app, so the adapter's real .post() path runs against the mock server with
    # no external network. Routing is by path, so the connector base_url is
    # irrelevant to which endpoint is hit.
    with TestClient(mock_app) as client:
        yield client


def test_live_write_success_is_truthful(asgi_client, monkeypatch):
    # Valid credential -> mock server returns 200 -> adapter reports success.
    monkeypatch.setenv("ASTRASOC_SECRET_TEST_SLACK_TOKEN", "mock-valid-token")
    conn = _live_slack_connector("vault://test/slack#token")
    adapter = get_adapter(conn, http_client=asgi_client)

    out = adapter.execute_action("notify_team", {"channel": "#soc"})
    assert out["live"] is True
    assert out["success"] is True
    assert out["status_code"] == 200
    assert "simulated" not in out  # this is a real transport call, not simulated


def test_live_write_auth_failure_is_not_fabricated(asgi_client, monkeypatch):
    # Wrong credential -> mock server returns 401 -> adapter MUST report failure.
    monkeypatch.setenv("ASTRASOC_SECRET_TEST_SLACK_TOKEN", "wrong-token")
    conn = _live_slack_connector("vault://test/slack#token")
    adapter = get_adapter(conn, http_client=asgi_client)

    out = adapter.execute_action("notify_team", {"channel": "#soc"})
    assert out["live"] is True
    assert out["success"] is False
    assert out["status_code"] == 401


def test_live_write_without_secret_reports_not_configured(asgi_client, monkeypatch):
    # No resolvable secret -> honest not-sent result, no network call fabricated.
    monkeypatch.delenv("ASTRASOC_SECRET_TEST_SLACK_TOKEN", raising=False)
    conn = _live_slack_connector("vault://test/slack#token")
    adapter = get_adapter(conn, http_client=asgi_client)

    out = adapter.execute_action("notify_team", {"channel": "#soc"})
    assert out["success"] is False
    assert out["error"] == "missing_secret"


def test_live_write_blocked_without_write_permission(asgi_client):
    conn = _live_slack_connector("vault://test/slack#token", can_write=False)
    adapter = get_adapter(conn, http_client=asgi_client)
    with pytest.raises(PermissionError):
        adapter.execute_action("notify_team", {"channel": "#soc"})


def test_endpoint_control_vendor_live_write_still_not_implemented():
    # CrowdStrike-style endpoint control has no generic single-POST contract; we
    # refuse to guess an API rather than fake a response.
    os.environ["ASTRASOC_SECRET_TEST_CS_TOKEN"] = "mock-valid-token"
    conn = Connector(
        name="CrowdStrike (live)", kind="crowdstrike_falcon", category="edr",
        enabled=True, base_url="http://mock-cs", use_mock=False, can_write=True,
    )
    conn.credential_refs = [
        ConnectorCredentialReference(field="api_token",
                                     secret_ref="vault://test/cs#token")
    ]
    adapter = get_adapter(conn)
    with pytest.raises(NotImplementedError):
        adapter.execute_action("isolate_endpoint", {"device_id": "abc"})
