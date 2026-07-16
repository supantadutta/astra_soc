"""Cross-cutting HTTP middleware: request IDs and a simple rate limiter."""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-response-time-ms"] = f"{(time.perf_counter() - start) * 1000:.1f}"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window-ish sliding limiter keyed by client IP.

    In-memory (fine for demo/single-node). Production points this at Redis via
    ASTRASOC_REDIS_URL; the interface is identical.
    """

    def __init__(self, app, per_minute: int | None = None) -> None:
        super().__init__(app)
        self.per_minute = per_minute or settings.rate_limit_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        # Never rate-limit the health probe or the SSE stream.
        if request.url.path in ("/health", "/api/v1/health/live") or request.url.path.endswith("/stream"):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        now = time.time()
        window = self._hits[client]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited",
                         "message": "Too many requests. Slow down.",
                         "request_id": getattr(request.state, "request_id", None)},
                headers={"retry-after": "10"},
            )
        window.append(now)
        return await call_next(request)
