"""Cross-cutting HTTP middleware: client IP, request IDs, security headers,
body-size limit and a per-client rate limiter."""
from __future__ import annotations

import hashlib
import ipaddress
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

MAX_BODY_BYTES = 5 * 1024 * 1024


def _trusted_networks() -> list[ipaddress._BaseNetwork]:
    nets = []
    for part in settings.trusted_proxies.split(","):
        part = part.strip()
        if part:
            try:
                nets.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                continue
    return nets


_TRUSTED = _trusted_networks()


def client_ip(request: Request) -> str:
    """The real client address. ``X-Forwarded-For`` is honoured only when the
    direct peer is a configured trusted proxy (otherwise it is spoofable)."""
    peer = request.client.host if request.client else "unknown"
    if not _TRUSTED:
        return peer
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not any(peer_ip in n for n in _TRUSTED):
        return peer
    chain = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    # Walk from the right, skipping our own trusted proxies.
    for hop in reversed(chain):
        try:
            if not any(ipaddress.ip_address(hop) in n for n in _TRUSTED):
                return hop
        except ValueError:
            return peer
    return peer


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        request_id = rid if (rid and len(rid) <= 64 and rid.replace("-", "").isalnum()) else uuid.uuid4().hex
        request.state.request_id = request_id
        request.state.client_ip = client_ip(request)
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-response-time-ms"] = f"{(time.perf_counter() - start) * 1000:.1f}"
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={
                "error": "payload_too_large", "message": f"Request body exceeds {MAX_BODY_BYTES} bytes."})
        response = await call_next(request)
        h = response.headers
        h.setdefault("x-content-type-options", "nosniff")
        h.setdefault("x-frame-options", "DENY")
        h.setdefault("referrer-policy", "no-referrer")
        h.setdefault("permissions-policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault("cross-origin-opener-policy", "same-origin")
        if not request.url.path.startswith("/api/docs") and not request.url.path.startswith("/api/redoc"):
            h.setdefault("content-security-policy", "default-src 'none'; frame-ancestors 'none'")
        if request.url.path.startswith("/api/v1/") and request.url.path != "/api/v1/stream":
            h.setdefault("cache-control", "no-store")
        if settings.is_production:
            h.setdefault("strict-transport-security", "max-age=31536000; includeSubDomains")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter (in-memory, per process): keyed by credential for
    authenticated requests and by client IP otherwise.

    Authentication endpoints get a much tighter budget to slow credential
    stuffing (on top of per-account lockout). Multi-replica deployments
    should front this with the ingress controller's rate limiting."""

    def __init__(self, app, per_minute: int | None = None) -> None:
        super().__init__(app)
        self.per_minute = per_minute or settings.rate_limit_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ("/health", "/api/v1/health/live", "/api/v1/health/ready", "/api/v1/stream"):
            return await call_next(request)
        ip = client_ip(request)
        is_auth = path in ("/api/v1/auth/login", "/api/v1/auth/refresh")
        credential = request.headers.get("authorization") or request.headers.get("x-api-key")
        if is_auth:
            key = f"auth:{ip}"
        elif credential:
            # Authenticated traffic is budgeted per credential, so users behind
            # one NAT / reverse proxy do not throttle each other. (Unverified
            # here; an invalid credential still costs the caller a 401.)
            key = "cred:" + hashlib.sha256(credential.encode()).hexdigest()[:24]
        else:
            key = ip
        limit = (settings.auth_rate_limit_per_minute
                 if is_auth and settings.environment != "test" else self.per_minute)
        now = time.time()
        window = self._hits[key]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= limit:
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "message": "Too many requests. Slow down.",
                         "request_id": getattr(request.state, "request_id", None)},
                headers={"retry-after": "10"},
            )
        window.append(now)
        if len(self._hits) > 50_000:  # bound memory under scanning
            self._hits.clear()
        return await call_next(request)
