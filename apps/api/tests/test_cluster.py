"""Multi-replica coordination: leader election, cross-replica event fan-out
and database-backed generator control. PostgreSQL-only parts are skipped on
SQLite (run the suite with ASTRASOC_TEST_DATABASE_URL to exercise them)."""
from __future__ import annotations

import os
import random
import time

import pytest

PG = (os.environ.get("ASTRASOC_TEST_DATABASE_URL") or "").startswith("postgresql")
needs_pg = pytest.mark.skipif(not PG, reason="needs PostgreSQL (ASTRASOC_TEST_DATABASE_URL)")


def _wait(predicate, timeout: float = 8.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


@needs_pg
def test_exactly_one_replica_leads_and_leadership_fails_over(client):
    from astrasoc.services.cluster import LeaderElection, libpq_dsn

    dsn, key = libpq_dsn(), random.randint(1, 2**31)
    a, b = LeaderElection(dsn=dsn, key=key), LeaderElection(dsn=dsn, key=key)
    try:
        assert a.try_acquire() is True
        assert b.try_acquire() is False          # a holds the lock
        assert a.try_acquire() is True           # keep-alive keeps it
        a.release()                              # a "dies": its session closes
        assert b.try_acquire() is True           # b takes over
        assert a.try_acquire() is False
    finally:
        a.release()
        b.release()


@needs_pg
def test_events_fan_out_to_other_replicas_without_echo(client):
    from astrasoc.services.cluster import PgEventBridge, libpq_dsn
    from astrasoc.services.events import Event, EventBus

    dsn = libpq_dsn()
    bus_a, bus_b = EventBus(), EventBus()
    bridge_a, bridge_b = PgEventBridge(bus_a, dsn, "replica-a"), PgEventBridge(bus_b, dsn, "replica-b")
    bridge_a.start()
    bridge_b.start()
    try:
        tenant = f"t-{random.randint(0, 10**9)}"
        # The listener needs a moment to LISTEN; keep publishing until B hears one.
        assert _wait(lambda: (bus_a.publish_soon(Event(type="probe", scope="DEMO", tenant_id=tenant)),
                              bool(bus_b.recent(tenant, "DEMO")))[1], timeout=10)
        bus_a.publish_soon(Event(type="incident.created", scope="DEMO", tenant_id=tenant,
                                 data={"incident_id": "abc", "key": "INC-9"}))
        assert _wait(lambda: any(e.type == "incident.created" for e in bus_b.recent(tenant, "DEMO")))
        relayed = next(e for e in bus_b.recent(tenant, "DEMO") if e.type == "incident.created")
        assert relayed.data["key"] == "INC-9"
        # A never re-receives its own events, and B does not forward relayed ones back.
        time.sleep(0.5)
        assert sum(e.type == "incident.created" for e in bus_a.recent(tenant, "DEMO")) == 1
        assert bridge_b.forwarded == 0
        # Tenant isolation holds for relayed events too.
        assert bus_b.recent("some-other-tenant", "DEMO") == []
    finally:
        bridge_a.stop()
        bridge_b.stop()


def test_generator_control_is_shared_through_the_database(client):
    from astrasoc.seed.engine import generator_state, set_generator

    try:
        assert set_generator(paused=True, speed=4)["paused"] is True
        state = generator_state()                 # read back from the DB, not process memory
        assert state["paused"] is True and state["speed"] == 4.0
        assert set_generator(speed=99)["speed"] == 10.0  # clamped
    finally:
        set_generator(paused=False, speed=1.0)


def test_in_process_migration_keeps_application_logging(tmp_path, monkeypatch):
    """Regression: alembic's fileConfig() disabled every existing logger when
    the app auto-migrated, silencing all application logs in production."""
    import logging

    from alembic import command
    from astrasoc.config import settings
    from astrasoc.db import _alembic_config

    app_logger = logging.getLogger("astrasoc")
    child = logging.getLogger("astrasoc.cluster")
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'mig.db'}")
    command.upgrade(_alembic_config(), "head")
    assert app_logger.disabled is False and child.disabled is False


def test_open_live_stream_does_not_block_shutdown(tmp_path):
    """Regression: an open SSE stream (every signed-in browser has one) held
    a stopping replica until the graceful-shutdown timeout, because
    sse-starlette's shutdown hook never engaged under uvicorn >= 0.29.
    Runs a real server process, since the bug lives in signal handling."""
    import signal
    import socket
    import subprocess
    import sys
    import threading
    from pathlib import Path

    import httpx

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "ASTRASOC_ENVIRONMENT": "demo",
           "ASTRASOC_DATABASE_URL": f"sqlite:///{tmp_path / 'shutdown.db'}",
           "ASTRASOC_DEMO_SEED_ON_STARTUP": "false"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "astrasoc.main:app", "--host", "127.0.0.1",
         "--port", str(port)],
        cwd=Path(__file__).resolve().parents[1], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}/api/v1"
    try:
        def ready() -> bool:
            assert proc.poll() is None, "API process exited during startup"
            try:
                return httpx.get(f"{base}/health/ready", timeout=1).status_code == 200
            except httpx.HTTPError:
                return False

        assert _wait(ready, timeout=90), "API did not become ready"
        token = httpx.post(f"{base}/auth/login", json={
            "email": "manager@acme.io", "password": "Demo!Pass123"}).json()["access_token"]
        ticket = httpx.post(f"{base}/stream/ticket",
                            headers={"Authorization": f"Bearer {token}"}).json()["ticket"]
        opened = threading.Event()

        def consume() -> None:
            try:
                with httpx.stream("GET", f"{base}/stream", params={"ticket": ticket},
                                  timeout=None) as r:
                    opened.set()
                    for _ in r.iter_bytes():
                        pass
            except httpx.HTTPError:
                pass

        threading.Thread(target=consume, daemon=True).start()
        assert opened.wait(10), "stream did not open"
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=15)  # TimeoutExpired = the stream held the process
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
