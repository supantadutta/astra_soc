"""Auth request/response schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # Not EmailStr: that rejects internal domains (corp.local) that account
    # creation accepts. Unknown or malformed addresses simply fail with 401.
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1)
    # "cookie": browser session in HttpOnly cookies; "token": tokens in the
    # response body (CLIs and integrations).
    session: Literal["cookie", "token"] = "token"


class MFALoginRequest(BaseModel):
    mfa_token: str = Field(..., min_length=10, max_length=2000)
    code: str | None = Field(default=None, max_length=12)
    recovery_code: str | None = Field(default=None, max_length=32)
    session: Literal["cookie", "token"] = "token"


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class MeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    tenant_id: str
    roles: list[str]
    permissions: list[str]
    is_service_account: bool
    # Tenant context the request is acting in (after any X-Tenant-ID switch).
    tenant_slug: str = ""
    tenant_name: str = ""
    tenant_kind: str = ""
    # MSSP delegation: where the user really belongs and how they got here.
    home_tenant_id: str | None = None
    home_tenant_slug: str = ""
    home_permissions: list[str] = []
    delegated_via: str | None = None
    # Authentication strength.
    mfa_enabled: bool = False
    mfa_verified: bool = False
    tenant_requires_mfa: bool = False


class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=list)
    expires_in_days: int | None = None


class APIKeyCreated(BaseModel):
    id: str
    name: str
    prefix: str
    api_key: str  # shown once
    scopes: list[str]
