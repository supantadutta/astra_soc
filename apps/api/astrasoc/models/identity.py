"""Tenant, identity, RBAC, and session models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import GUID, Base
from .base import TimestampMixin, UUIDMixin


class Tenant(UUIDMixin, TimestampMixin, Base):
    """A tenant in the MSSP hierarchy.

    ``provider`` tenants are managed-security providers (the platform operator
    is the root provider), ``reseller`` tenants resell a provider's service,
    and ``customer`` tenants are the organisations whose security is managed.
    Provider/reseller staff reach descendant customers only through the
    delegated-access rules in :mod:`astrasoc.services.tenancy`.
    """

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120), unique=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    kind: Mapped[str] = mapped_column(String(16), default="customer", index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # onboarding | active | suspended | offboarding
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    service_tier: Mapped[str] = mapped_column(String(24), default="professional")
    # Data residency region (e.g. "eu", "us", "apac"); LLM providers and
    # connectors must be compatible with it.
    region: Mapped[str] = mapped_column(String(16), default="global")
    # Per-severity SLA targets in minutes: {"critical": {"ack": 15, "resolve": 240}, ...}
    sla_policy: Mapped[dict] = mapped_column(default=dict)
    # Escalation contacts: [{"name","email","phone","role","level","notify_on":[...]}]
    contacts: Mapped[list] = mapped_column(default=list)
    # White-label presentation: {"display_name","logo_url","primary_color","support_email"}
    branding: Mapped[dict] = mapped_column(default=dict)
    contract_start: Mapped[datetime | None] = mapped_column(nullable=True)
    contract_end: Mapped[datetime | None] = mapped_column(nullable=True)
    # Guardrails & customer-controlled delegation policy, e.g.
    # {"delegation": {"allow_provider_access": true, "allowed_roles": [...]},
    #  "customer_approval_actions": ["isolate_endpoint"], "private_model_only": false}
    settings: Mapped[dict] = mapped_column(default=dict)

    users: Mapped[list[User]] = relationship(back_populates="tenant")


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(255), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    # Salted PBKDF2 hash. Never a plaintext or reversible value.
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_service_account: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Brute-force protection.
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # MFA (TOTP). Secrets are Fernet-encrypted; recovery codes are hashed.
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_pending_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_recovery_hashes: Mapped[list] = mapped_column(default=list)
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mfa_enrolled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # ABAC attributes (e.g. clearance, allowed data classifications).
    attributes: Mapped[dict] = mapped_column(default=dict)

    tenant: Mapped[Tenant] = relationship(back_populates="users")
    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)

    # tenant_id NULL => a platform-global built-in role template.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    # List of permission strings, e.g. "incident:read", "action:execute".
    permissions: Mapped[list] = mapped_column(default=list)


class Permission(UUIDMixin, Base):
    """Catalogue of every permission the platform recognizes."""

    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")


class UserRole(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("roles.id", ondelete="CASCADE"), index=True
    )
    # Temporary elevation support.
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship()


class Session(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Session id carried in access tokens ("sid"); revoking the session
    # invalidates every access token issued for it.
    sid: Mapped[str] = mapped_column(String(64), index=True, default="")
    refresh_token_hash: Mapped[str] = mapped_column(String(255), index=True)
    # Refresh tokens rotate on every use; presenting a superseded token is
    # treated as theft and revokes the session.
    previous_token_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Whether this session was established with a second factor.
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    expires_at: Mapped[datetime] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class APIKey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(12), index=True)
    key_hash: Mapped[str] = mapped_column(String(255))
    scopes: Mapped[list] = mapped_column(default=list)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
