"""In-process async event bus backing the SSE live stream.

* Thread-safe: most publishers run in worker threads (sync FastAPI handlers,
  background ticks). ``publish_soon`` hands the event to the event loop the
  bus was bound to at startup via ``call_soon_threadsafe`` — events are
  delivered live, not just recorded.
* Tenant-isolated: every subscriber declares the tenants (and, for its
  acting tenant, the data scope) it may see. Events without a tenant are
  never delivered to subscribers.

* Cross-replica: with PostgreSQL, :mod:`astrasoc.services.cluster` installs a
  forwarder that NOTIFYs other replicas, and relays their events here through
  :meth:`EventBus.publish_remote` (which does not forward again).
"""
from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Event:
    type: str
    scope: str
    tenant_id: str | None
    data: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def sse(self) -> dict[str, str]:
        return {
            "event": self.type,
            "data": json.dumps({
                "type": self.type, "scope": self.scope, "tenant_id": self.tenant_id,
                "ts": self.ts, **self.data,
            }, default=str),
        }


@dataclass(eq=False)
class Subscription:
    """What a subscriber may receive: events of ``tenant_id`` in ``scope``,
    plus any-scope events of the extra (e.g. provider home) tenants."""

    tenant_id: str
    scope: str
    extra_tenants: frozenset[str] = frozenset()
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000))

    def allows(self, ev: Event) -> bool:
        if ev.tenant_id is None:
            return False
        if ev.tenant_id == self.tenant_id:
            return ev.scope == self.scope
        return ev.tenant_id in self.extra_tenants


class EventBus:
    def __init__(self, history: int = 500) -> None:
        self._subs: set[Subscription] = set()
        self._recent: deque[Event] = deque(maxlen=history)
        self._counter = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._forwarder: Callable[[Event], None] | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def set_forwarder(self, forwarder: Callable[[Event], None] | None) -> None:
        """Called (non-blocking) for every locally published event."""
        self._forwarder = forwarder

    def _forward(self, event: Event) -> None:
        fwd = self._forwarder
        if fwd is not None:
            fwd(event)

    def _deliver(self, event: Event) -> None:
        for sub in list(self._subs):
            if sub.allows(event):
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:  # slow consumer — drop rather than block
                    pass

    async def publish(self, event: Event) -> None:
        with self._lock:
            self._counter += 1
            self._recent.append(event)
        self._deliver(event)
        self._forward(event)

    def publish_soon(self, event: Event) -> None:
        """Publish from any thread."""
        self._forward(event)
        self._record_and_deliver(event)

    def publish_remote(self, event: Event) -> None:
        """Deliver an event published on another replica (never re-forwarded)."""
        self._record_and_deliver(event)

    def _record_and_deliver(self, event: Event) -> None:
        with self._lock:
            self._counter += 1
            self._recent.append(event)
        loop = self._loop
        if loop is None or loop.is_closed():
            return  # no loop yet (seeding / tests): recorded in history only
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(event)
        else:
            loop.call_soon_threadsafe(self._deliver, event)

    def subscribe(self, tenant_id: str, scope: str, extra_tenants: set[str] | None = None) -> Subscription:
        sub = Subscription(tenant_id=tenant_id, scope=scope,
                           extra_tenants=frozenset(extra_tenants or ()))
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    def recent(self, tenant_id: str, scope: str, limit: int = 50,
               extra_tenants: set[str] | None = None) -> list[Event]:
        probe = Subscription(tenant_id=tenant_id, scope=scope,
                             extra_tenants=frozenset(extra_tenants or ()))
        with self._lock:
            items = [e for e in self._recent if probe.allows(e)]
        return items[-limit:]

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    @property
    def total_published(self) -> int:
        return self._counter


bus = EventBus()
