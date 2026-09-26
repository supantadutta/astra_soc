"""The request principal — the authenticated subject plus resolved authority."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .permissions import role_has_permission


@dataclass
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    full_name: str
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    is_service_account: bool = False
    allowed_classifications: list[str] = field(default_factory=list)
    session_id: str | None = None
    tenant_slug: str = ""
    # MSSP delegation: when a provider user acts inside a customer tenant,
    # tenant_id/permissions describe the customer context and these fields
    # record where the user really comes from.
    home_tenant_id: uuid.UUID | None = None
    home_tenant_slug: str = ""
    home_permissions: list[str] = field(default_factory=list)
    delegated_via: str | None = None  # platform | break_glass | provider | grant
    grant_id: uuid.UUID | None = None
    # Authentication strength of this request.
    mfa_verified: bool = False       # interactive session established with a second factor
    via_api_key: bool = False
    via_cookie: bool = False

    @property
    def is_platform_admin(self) -> bool:
        return role_has_permission(self.home_permissions or self.permissions, "platform:admin")

    @property
    def is_delegated(self) -> bool:
        return self.delegated_via is not None

    def has_home(self, permission: str) -> bool:
        """Permission check against the caller's HOME tenant (portfolio APIs)."""
        return role_has_permission(self.home_permissions or self.permissions, permission)

    def require_home(self, permission: str) -> None:
        from fastapi import HTTPException, status

        if not self.has_home(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
                "error": "forbidden", "message": f"Missing required permission: {permission}",
                "required_permission": permission})

    def has(self, permission: str) -> bool:
        return role_has_permission(self.permissions, permission)

    def require(self, permission: str) -> None:
        from fastapi import HTTPException, status

        if not self.has(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "forbidden",
                    "message": f"Missing required permission: {permission}",
                    "required_permission": permission,
                },
            )

    @property
    def label(self) -> str:
        base = f"{self.full_name} <{self.email}>"
        if self.delegated_via:
            tag = "BREAK-GLASS " if self.delegated_via == "break_glass" else ""
            return f"{base} [{tag}via {self.home_tenant_slug}/{self.delegated_via}]"
        return base
