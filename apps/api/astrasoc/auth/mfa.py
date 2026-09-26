"""Multi-factor authentication primitives.

* **TOTP** (RFC 6238: HMAC-SHA1, 6 digits, 30-second steps) compatible with
  every mainstream authenticator app. Verification accepts ±1 step of clock
  drift and rejects any step at or before the last one used, so a code can
  never be replayed.
* **Secrets at rest** are encrypted with Fernet (AES-128-CBC + HMAC-SHA256)
  under a key derived (HKDF-SHA256) from ``ASTRASOC_DATA_ENCRYPTION_KEY``, or
  from the audit key when no dedicated key is configured.
* **Recovery codes** are random, shown once, stored only as salted hashes and
  consumed on use.
* **Challenge tokens** are short-lived JWTs that carry a half-finished login
  between the password step and the second factor. They grant nothing else.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import jwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import settings

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
CHALLENGE_TTL_SECONDS = 300
ENROLLMENT_TTL_SECONDS = 900


# --- TOTP ------------------------------------------------------------------
def generate_secret() -> str:
    """A 160-bit secret, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key_bytes(secret_b32: str) -> bytes:
    padded = secret_b32.upper() + "=" * (-len(secret_b32) % 8)
    return base64.b32decode(padded)


def hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp(secret_b32: str, at: float | None = None, digits: int = DIGITS) -> str:
    step = int((time.time() if at is None else at) // STEP_SECONDS)
    return hotp(_key_bytes(secret_b32), step, digits)


def verify_totp(secret_b32: str, code: str, last_step: int | None,
                at: float | None = None) -> int | None:
    """Return the matched time step, or None. Steps at or before ``last_step``
    are refused (replay protection)."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now_step = int((time.time() if at is None else at) // STEP_SECONDS)
    key = _key_bytes(secret_b32)
    for step in range(now_step - DRIFT_STEPS, now_step + DRIFT_STEPS + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(hotp(key, step), code):
            return step
    return None


def provisioning_uri(secret_b32: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    return (f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


# --- Encryption at rest ------------------------------------------------------
def _fernet() -> Fernet:
    material = (settings.data_encryption_key or settings.audit_signing_key).encode()
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"astrasoc-data-encryption",
               info=b"mfa-secret-v1").derive(material)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret_b32: str) -> str:
    return _fernet().encrypt(secret_b32.encode()).decode()


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


# --- Recovery codes ------------------------------------------------------------
def _normalise_recovery(code: str) -> str:
    return "".join(ch for ch in (code or "").lower() if ch.isalnum())


def generate_recovery_codes(n: int = RECOVERY_CODE_COUNT) -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"  # no ambiguous characters
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(2))
            for _ in range(n)]


def hash_recovery_code(code: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", _normalise_recovery(code).encode(), salt.encode(), 50_000)
    return f"{salt}${digest.hex()}"


def consume_recovery_code(code: str, hashes_: list[str]) -> list[str] | None:
    """Return the remaining hashes if ``code`` matched one (which is removed),
    otherwise None."""
    norm = _normalise_recovery(code)
    if len(norm) != 10:
        return None
    for i, stored in enumerate(hashes_ or []):
        salt, _, digest = stored.partition("$")
        calc = hashlib.pbkdf2_hmac("sha256", norm.encode(), salt.encode(), 50_000).hex()
        if hmac.compare_digest(calc, digest):
            return [h for j, h in enumerate(hashes_) if j != i]
    return None


# --- Challenge tokens -----------------------------------------------------------
def issue_challenge(user_id: uuid.UUID, kind: str) -> str:
    """kind: ``mfa`` (second factor pending) or ``mfa_enroll`` (the tenant
    requires MFA and the user has not enrolled yet)."""
    ttl = CHALLENGE_TTL_SECONDS if kind == "mfa" else ENROLLMENT_TTL_SECONDS
    now = datetime.now(UTC)
    return jwt.encode({"sub": str(user_id), "type": kind, "iat": now,
                       "exp": now + timedelta(seconds=ttl), "jti": secrets.token_hex(8)},
                      settings.jwt_secret, algorithm=settings.jwt_algorithm)


def read_challenge(token: str, kind: str) -> uuid.UUID | None:
    try:
        claims = jwt.decode(token or "", settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if claims.get("type") != kind:
        return None
    try:
        return uuid.UUID(str(claims.get("sub")))
    except ValueError:
        return None


# --- Tenant policy ---------------------------------------------------------------
def tenant_requires_mfa(tenant) -> bool:
    return bool(((tenant.settings or {}).get("security") or {}).get("require_mfa")) if tenant else False
