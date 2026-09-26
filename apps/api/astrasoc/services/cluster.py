"""Coordination between API replicas, using PostgreSQL only.

* **Event fan-out** — every replica delivers events to its own SSE clients
  and also ``NOTIFY``s them on a channel; each replica ``LISTEN``s and
  relays events published elsewhere. An analyst therefore sees every event
  regardless of which replica their stream is connected to.
* **Leader election** — background workers that must run exactly once
  (SLA breach sweeper, demo generator) run only on the replica holding a
  session-level advisory lock. If that replica dies, its connection closes,
  the lock is released and another replica takes over within seconds.

With SQLite (single process by definition) neither is needed: the process
is always the leader and the in-process bus is complete.
"""
from __future__ import annotations

import json
import logging
import queue
import select
import threading
import time
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.engine import make_url

from ..config import settings

if TYPE_CHECKING:  # pragma: no cover
    from .events import Event, EventBus

logger = logging.getLogger("astrasoc.cluster")

REPLICA_ID = uuid.uuid4().hex[:12]
CHANNEL = "astrasoc_events"
LEADER_LOCK_KEY = 0x41535445  # "ASTE"
_NOTIFY_LIMIT = 7800  # PostgreSQL caps NOTIFY payloads at 8000 bytes


def is_clustered() -> bool:
    return not settings.is_sqlite


def libpq_dsn(url: str | None = None) -> str:
    """SQLAlchemy URL → libpq connection URI for psycopg2.connect()."""
    u = make_url(url or settings.database_url).set(drivername="postgresql")
    return u.render_as_string(hide_password=False)


def _connect(dsn: str):
    import psycopg2
    import psycopg2.extensions

    conn = psycopg2.connect(dsn, connect_timeout=10, application_name=f"astrasoc-{REPLICA_ID}")
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


# --- Leader election -----------------------------------------------------------------
class LeaderElection:
    """Holds a PostgreSQL advisory lock on a dedicated connection while this
    replica is the leader. Re-checks every ``interval`` seconds."""

    def __init__(self, dsn: str | None = None, key: int = LEADER_LOCK_KEY, interval: float = 10.0) -> None:
        self._dsn = dsn
        self._key = key
        self._interval = interval
        self._conn = None
        self._leader = not is_clustered() if dsn is None else False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_leader(self) -> bool:
        return self._leader

    def try_acquire(self) -> bool:
        """One election round (also used directly by tests)."""
        try:
            if self._conn is None or self._conn.closed:
                self._conn = _connect(self._dsn or libpq_dsn())
                self._leader = False
            with self._conn.cursor() as cur:
                if self._leader:
                    cur.execute("SELECT 1")  # keep-alive: lock is held while the session lives
                else:
                    cur.execute("SELECT pg_try_advisory_lock(%s)", (self._key,))
                    if cur.fetchone()[0]:
                        self._leader = True
                        logger.info("Replica %s is now the leader", REPLICA_ID)
        except Exception as exc:  # noqa: BLE001 — lose leadership, retry next round
            if self._leader:
                logger.warning("Replica %s lost leadership: %s", REPLICA_ID, exc)
            self._leader = False
            self.release()
        return self._leader

    def release(self) -> None:
        conn, self._conn = self._conn, None
        self._leader = False if (self._dsn or is_clustered()) else self._leader
        if conn is not None and not conn.closed:
            try:
                conn.close()  # closing the session releases the advisory lock
            except Exception:  # noqa: BLE001
                pass

    def start(self) -> None:
        if not is_clustered() and self._dsn is None:
            return  # single process: always leader
        def loop() -> None:
            while not self._stop.is_set():
                self.try_acquire()
                self._stop.wait(self._interval)
            self.release()
        self._thread = threading.Thread(target=loop, name="astrasoc-leader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.release()


# --- Event fan-out -------------------------------------------------------------------
class PgEventBridge:
    """Forwards locally published events to other replicas and relays theirs."""

    def __init__(self, bus: EventBus, dsn: str | None = None, replica_id: str = REPLICA_ID) -> None:
        self._bus = bus
        self._dsn = dsn or libpq_dsn()
        self._replica = replica_id
        self._outbox: queue.Queue = queue.Queue(maxsize=10_000)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.forwarded = 0
        self.received = 0
        self.dropped = 0

    # called by EventBus for every local publish (any thread, never blocks)
    def forward(self, event: Event) -> None:
        try:
            self._outbox.put_nowait(event)
        except queue.Full:
            self.dropped += 1

    def _payload(self, event: Event) -> str | None:
        body = {"o": self._replica, "type": event.type, "scope": event.scope,
                "tenant_id": event.tenant_id, "ts": event.ts, "data": event.data}
        text = json.dumps(body, default=str, separators=(",", ":"))
        if len(text.encode()) > _NOTIFY_LIMIT:
            body["data"] = {k: v for k, v in event.data.items() if isinstance(v, str | int | float | bool)
                            and len(str(v)) < 200}
            body["data"]["truncated"] = True
            text = json.dumps(body, default=str, separators=(",", ":"))
            if len(text.encode()) > _NOTIFY_LIMIT:
                return None
        return text

    def _sender(self) -> None:
        conn = None
        while not self._stop.is_set():
            try:
                event = self._outbox.get(timeout=0.5)
            except queue.Empty:
                continue
            payload = self._payload(event)
            if payload is None:
                self.dropped += 1
                continue
            for attempt in range(2):
                try:
                    if conn is None or conn.closed:
                        conn = _connect(self._dsn)
                    with conn.cursor() as cur:
                        cur.execute("SELECT pg_notify(%s, %s)", (CHANNEL, payload))
                    self.forwarded += 1
                    break
                except Exception:  # noqa: BLE001 — reconnect once, then drop
                    conn = None
                    if attempt:
                        self.dropped += 1
                        time.sleep(1)

    def _listener(self) -> None:
        from .events import Event

        backoff = 1.0
        while not self._stop.is_set():
            conn = None
            try:
                conn = _connect(self._dsn)
                with conn.cursor() as cur:
                    cur.execute(f"LISTEN {CHANNEL}")
                backoff = 1.0
                while not self._stop.is_set():
                    if select.select([conn], [], [], 1.0) == ([], [], []):
                        continue
                    conn.poll()
                    while conn.notifies:
                        note = conn.notifies.pop(0)
                        try:
                            msg = json.loads(note.payload)
                        except ValueError:
                            continue
                        if msg.get("o") == self._replica:
                            continue  # our own event: already delivered locally
                        self.received += 1
                        self._bus.publish_remote(Event(type=msg["type"], scope=msg["scope"],
                                                       tenant_id=msg.get("tenant_id"),
                                                       data=msg.get("data") or {}, ts=msg.get("ts")))
            except Exception as exc:  # noqa: BLE001 — reconnect with backoff
                logger.warning("Event listener reconnecting: %s", exc)
                self._stop.wait(backoff)
                backoff = min(30.0, backoff * 2)
            finally:
                if conn is not None and not conn.closed:
                    conn.close()

    def start(self) -> None:
        for target, name in ((self._sender, "astrasoc-events-out"), (self._listener, "astrasoc-events-in")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        self._bus.set_forwarder(self.forward)

    def stop(self) -> None:
        self._bus.set_forwarder(None)
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)

    def stats(self) -> dict:
        return {"replica": self._replica, "forwarded": self.forwarded, "received": self.received,
                "dropped": self.dropped}


# --- Process-wide runtime (set up by the application lifespan) ------------------------
class _Runtime:
    leader: LeaderElection | None = None
    bridge: PgEventBridge | None = None


runtime = _Runtime()


def cluster_stats() -> dict | None:
    """Cross-replica status for Platform Health (None when single-process)."""
    if runtime.bridge is None:
        return None
    return {**runtime.bridge.stats(), "leader": bool(runtime.leader and runtime.leader.is_leader)}
