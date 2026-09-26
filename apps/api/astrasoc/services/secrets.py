"""Vault-compatible secret-manager interface.

Secrets are referenced by URI (``vault://path#field``, ``env://VAR``,
``file://path``). The database and API only ever store *references*, never
plaintext. In the demo profile a local encrypted-at-rest-simulated store backs
``vault://`` refs; production points the same interface at HashiCorp Vault /
AWS Secrets Manager without changing callers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class SecretRef:
    scheme: str
    path: str
    field: str | None = None

    @classmethod
    def parse(cls, ref: str) -> SecretRef:
        if "://" not in ref:
            raise ValueError(f"Invalid secret reference: {ref!r}")
        scheme, rest = ref.split("://", 1)
        field = None
        if "#" in rest:
            rest, field = rest.split("#", 1)
        return cls(scheme=scheme, path=rest, field=field)


class SecretManager:
    """Abstract secret backend."""

    def resolve(self, ref: str) -> str | None:  # pragma: no cover - interface
        raise NotImplementedError

    def exists(self, ref: str) -> bool:
        try:
            return self.resolve(ref) is not None
        except Exception:
            return False


class LocalSecretManager(SecretManager):
    """Backend for the demo/dev profile.

    * ``env://VAR`` reads an environment variable.
    * ``vault://path#field`` maps to env var ``ASTRASOC_SECRET_<PATH>_<FIELD>``
      (uppercased, non-alphanumerics -> ``_``). This lets an operator supply a
      real API key for a provider/connector via environment without ever
      storing it in the DB.
    """

    def resolve(self, ref: str) -> str | None:
        parsed = SecretRef.parse(ref)
        if parsed.scheme == "env":
            return os.environ.get(parsed.path)
        if parsed.scheme == "file":
            try:
                with open(parsed.path, encoding="utf-8") as fh:
                    return fh.read().strip()
            except OSError:
                return None
        if parsed.scheme == "vault":
            key = _env_key(parsed.path, parsed.field)
            return os.environ.get(key)
        return None


def _env_key(path: str, field: str | None) -> str:
    base = f"ASTRASOC_SECRET_{path}"
    if field:
        base = f"{base}_{field}"
    return "".join(c if c.isalnum() else "_" for c in base).upper()


class VaultSecretManager(SecretManager):
    """HashiCorp Vault KV v2 backend.

    ``vault://tenants/acme/splunk#token`` reads field ``token`` from
    ``<mount>/data/tenants/acme/splunk``. Values are cached briefly so a hot
    path does not hit Vault on every request. ``env://``/``file://`` fall back
    to the local manager (and are still subject to the scheme policy).
    """

    def __init__(self, addr: str, token: str, mount: str = "secret", ttl: int = 60) -> None:
        self.addr = addr.rstrip("/")
        self.token = token
        self.mount = mount.strip("/")
        self.ttl = ttl
        self._cache: dict[str, tuple[float, str | None]] = {}
        self._local = LocalSecretManager()

    def resolve(self, ref: str) -> str | None:
        import time

        import httpx

        parsed = SecretRef.parse(ref)
        if parsed.scheme != "vault":
            return self._local.resolve(ref)
        hit = self._cache.get(ref)
        if hit and hit[0] > time.time():
            return hit[1]
        try:
            resp = httpx.get(f"{self.addr}/v1/{self.mount}/data/{parsed.path}",
                             headers={"X-Vault-Token": self.token}, timeout=5)
            value = None
            if resp.status_code == 200:
                data = (resp.json().get("data") or {}).get("data") or {}
                value = data.get(parsed.field or "value")
        except Exception:  # noqa: BLE001 — an unreachable Vault resolves to "not configured"
            value = None
        self._cache[ref] = (time.time() + self.ttl, value)
        return value


def _build_manager() -> SecretManager:
    from ..config import settings

    token = os.environ.get("ASTRASOC_VAULT_TOKEN") or os.environ.get("VAULT_TOKEN")
    if settings.vault_addr and token:
        return VaultSecretManager(settings.vault_addr, token,
                                  os.environ.get("ASTRASOC_VAULT_MOUNT", "secret"))
    return LocalSecretManager()


secret_manager: SecretManager = _build_manager()


SAFE_SCHEMES = {"vault"}
UNSAFE_SCHEMES = {"env", "file"}


class SecretRefError(ValueError):
    """A secret reference violates the reference policy."""


def _scheme_allowed(scheme: str) -> bool:
    from ..config import settings

    if scheme in SAFE_SCHEMES:
        return True
    return scheme in UNSAFE_SCHEMES and settings.allow_unsafe_secret_schemes


def tenant_secret_prefix(tenant_slug: str) -> str:
    return f"tenants/{tenant_slug}/"


def validate_secret_ref(ref: str, *, tenant_slug: str, platform_admin: bool) -> str:
    """Validate a tenant-supplied secret reference before it is stored.

    * Only ``vault://`` references are accepted by default. ``env://`` and
      ``file://`` read arbitrary process state, so they are reserved for
      operators who explicitly enable ``ASTRASOC_ALLOW_UNSAFE_SECRET_SCHEMES``.
    * Tenant users may only reference their own namespace
      (``vault://tenants/<slug>/...``). Platform administrators may reference
      shared platform secrets.
    """
    try:
        parsed = SecretRef.parse(ref.strip())
    except ValueError as exc:
        raise SecretRefError(str(exc)) from exc
    if not _scheme_allowed(parsed.scheme):
        raise SecretRefError(
            f"Secret scheme '{parsed.scheme}://' is not permitted; use vault:// references.")
    if parsed.scheme in UNSAFE_SCHEMES and not platform_admin:
        raise SecretRefError("Only platform administrators may use env:// or file:// references.")
    if parsed.scheme == "vault" and not platform_admin:
        if not parsed.path.startswith(tenant_secret_prefix(tenant_slug)):
            raise SecretRefError(
                f"Tenant secrets must live under vault://{tenant_secret_prefix(tenant_slug)}…")
    if ".." in parsed.path:
        raise SecretRefError("Path traversal is not allowed in secret references.")
    return ref.strip()


def resolve_secret(ref: str | None) -> str | None:
    if not ref:
        return None
    try:
        scheme = SecretRef.parse(ref).scheme
    except ValueError:
        return None
    if not _scheme_allowed(scheme):
        return None  # policy: disallowed schemes never resolve
    return secret_manager.resolve(ref)


def secret_configured(ref: str | None) -> bool:
    return resolve_secret(ref) is not None
