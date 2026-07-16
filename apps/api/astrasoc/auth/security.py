"""Cryptographic primitives: password hashing, JWT, API-key + result signing.

Passwords use PBKDF2-HMAC-SHA256 (pure stdlib) so the platform installs and
runs without a native bcrypt toolchain. JWTs are signed with the configured
HS256 secret. Nothing here logs or returns a plaintext secret.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from ..config import settings

_PBKDF2_ROUNDS = 240_000


# --- Passwords -----------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# --- JWT -----------------------------------------------------------------
def create_access_token(claims: dict[str, Any], ttl_seconds: int | None = None) -> str:
    now = datetime.now(UTC)
    ttl = ttl_seconds if ttl_seconds is not None else settings.access_token_ttl_seconds
    payload = {**claims, "iat": now, "exp": now + timedelta(seconds=ttl), "type": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(claims: dict[str, Any]) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=settings.refresh_token_ttl_seconds)
    payload = {**claims, "iat": now, "exp": exp, "type": "refresh", "jti": secrets.token_hex(16)}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, exp


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# --- API keys ------------------------------------------------------------
def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, hash). The full key is shown once, never stored."""
    prefix = "ask_" + secrets.token_hex(3)
    secret = secrets.token_urlsafe(32)
    full = f"{prefix}.{secret}"
    return full, prefix, hash_token(full)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- Result / audit signing ---------------------------------------------
def sign_payload(payload: bytes) -> str:
    """HMAC signature used for tool-result signing and audit chaining."""
    return hmac.new(settings.jwt_secret.encode(), payload, hashlib.sha256).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
