"""Auth request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class MeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    tenant_id: str
    roles: list[str]
    permissions: list[str]
    is_service_account: bool


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
