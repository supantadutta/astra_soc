"""Browser session cookies and CSRF protection.

Browsers authenticate with cookies the page's JavaScript cannot read:

* ``astrasoc_at``   access token, HttpOnly, sent to ``/api`` only
* ``astrasoc_rt``   refresh token, HttpOnly, sent to ``/api/v1/auth`` only
* ``astrasoc_csrf`` random CSRF token, readable by the page

All are ``SameSite=Strict`` and ``Secure`` in production. A state-changing
request authenticated by cookie must echo the CSRF cookie in the
``X-CSRF-Token`` header (double-submit), which a cross-site page cannot do.

Programmatic clients keep using ``Authorization: Bearer`` or ``X-API-Key``;
those are never subject to CSRF because browsers do not attach them
automatically.
"""
from __future__ import annotations

import hmac
import secrets

from fastapi import Request
from starlette.responses import Response

from ..config import settings

ACCESS_COOKIE = "astrasoc_at"
REFRESH_COOKIE = "astrasoc_rt"
CSRF_COOKIE = "astrasoc_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_ACCESS_PATH = "/api"
_REFRESH_PATH = "/api/v1/auth"


def set_session_cookies(response: Response, access: str, refresh: str) -> None:
    secure = settings.secure_cookies
    response.set_cookie(ACCESS_COOKIE, access, max_age=settings.access_token_ttl_seconds,
                        path=_ACCESS_PATH, httponly=True, secure=secure, samesite="strict")
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=settings.refresh_token_ttl_seconds,
                        path=_REFRESH_PATH, httponly=True, secure=secure, samesite="strict")
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32),
                        max_age=settings.refresh_token_ttl_seconds, path="/",
                        httponly=False, secure=secure, samesite="strict")


def clear_session_cookies(response: Response) -> None:
    secure = settings.secure_cookies
    for name, path in ((ACCESS_COOKIE, _ACCESS_PATH), (REFRESH_COOKIE, _REFRESH_PATH),
                       (CSRF_COOKIE, "/")):
        response.delete_cookie(name, path=path, secure=secure, httponly=name != CSRF_COOKIE,
                               samesite="strict")


def csrf_ok(request: Request) -> bool:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    return len(cookie) >= 16 and hmac.compare_digest(cookie, header)
