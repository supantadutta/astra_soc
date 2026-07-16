"""In-process async event bus backing the SSE live stream.

The demo profile does not require Kafka/Redpanda. This bus fans out platform
events (new alerts, incident updates, agent steps, approvals, actions, metric
ticks) to any connected SSE clients. In production the same publish() calls can
be pointed at Redpanda; the API layer is unchanged.

Events carry a ``scope`` (DEMO/LIVE) so a subscriber only receives events for
the mode it is watching.
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
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
                "type": self.type,
                "scope": self.scope,
                "tenant_id": self.tenant_id,
                "ts": self.ts,
                **self.data,
            }),
        }


class EventBus:
    def __init__(self, history: int = 200) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._recent: deque[Event] = deque(maxlen=history)
        self._counter = 0

    async def publish(self, event: Event) -> None:
        self._counter += 1
        self._recent.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer — drop rather than block
                pass

    def publish_soon(self, event: Event) -> None:
        """Fire-and-forget publish usable from sync code paths."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            # No running loop (e.g. seeding); just record in history.
            self._recent.append(event)

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def recent(self, scope: str, limit: int = 50) -> list[Event]:
        items = [e for e in self._recent if e.scope == scope]
        return items[-limit:]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def total_published(self) -> int:
        return self._counter


bus = EventBus()
