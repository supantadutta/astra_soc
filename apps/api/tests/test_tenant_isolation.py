"""Cross-tenant isolation is enforced by the backend, not the client.

We provision a second tenant directly in the DB, log in as its manager through
the real API, and prove that tenant cannot see or fetch the seeded tenant's
incidents. Isolation is a tenant_id filter applied server-side on every query.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from astrasoc.auth.security import hash_password
from astrasoc.db import SessionLocal
from astrasoc.models import Tenant, User, UserRole
from astrasoc.seed.bootstrap import _ensure_permissions, _ensure_roles

SECOND_EMAIL = "manager@globex.io"
SECOND_PASSWORD = "Globex!Pass123"


@pytest.fixture(scope="module")
def second_tenant_manager():
    """Create an isolated second tenant + manager user once for this module."""
    db = SessionLocal()
    try:
        existing = db.execute(
            select(Tenant).where(Tenant.slug == "globex")
        ).scalar_one_or_none()
        if existing is None:
            tenant = Tenant(name="Globex Corporation", slug="globex", settings={})
            db.add(tenant)
            db.flush()
            _ensure_permissions(db)
            roles = _ensure_roles(db, tenant.id)
            user = User(
                tenant_id=tenant.id, email=SECOND_EMAIL,
                full_name="Globex SOC Manager",
                password_hash=hash_password(SECOND_PASSWORD),
                attributes={"allowed_classifications": ["public", "internal"]},
            )
            db.add(user)
            db.flush()
            db.add(UserRole(user_id=user.id, role_id=roles["soc_manager"].id))
            db.commit()
    finally:
        db.close()
    return {"email": SECOND_EMAIL, "password": SECOND_PASSWORD}


def _login(client, creds) -> dict:
    r = client.post("/api/v1/auth/login", json=creds)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_second_tenant_sees_none_of_first_tenants_incidents(
    client, manager, second_tenant_manager
):
    # The seeded (acme) tenant has incidents.
    acme_items = client.get("/api/v1/incidents", headers=manager).json()["items"]
    assert len(acme_items) >= 1

    # The freshly created (globex) tenant has its own, empty scope.
    globex = _login(client, second_tenant_manager)
    globex_items = client.get("/api/v1/incidents", headers=globex).json()["items"]
    assert globex_items == []


def test_second_tenant_cannot_fetch_first_tenants_incident_by_id(
    client, manager, second_tenant_manager
):
    acme_items = client.get("/api/v1/incidents", headers=manager).json()["items"]
    target_id = acme_items[0]["id"]

    # Same id is directly reachable for its own tenant...
    assert client.get(f"/api/v1/incidents/{target_id}", headers=manager).status_code == 200

    # ...but a cross-tenant fetch is denied server-side (404, not leaked).
    globex = _login(client, second_tenant_manager)
    cross = client.get(f"/api/v1/incidents/{target_id}", headers=globex)
    assert cross.status_code == 404
