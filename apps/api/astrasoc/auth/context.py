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
        return f"{self.full_name} <{self.email}>"
