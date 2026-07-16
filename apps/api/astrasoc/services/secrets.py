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


# Swap this for a Vault-backed implementation in production via DI/config.
secret_manager: SecretManager = LocalSecretManager()


def resolve_secret(ref: str | None) -> str | None:
    if not ref:
        return None
    return secret_manager.resolve(ref)


def secret_configured(ref: str | None) -> bool:
    if not ref:
        return False
    return secret_manager.exists(ref)
