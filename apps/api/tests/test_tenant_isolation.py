"""Cross-tenant isolation is enforced by the backend, not the client.

Two peer customer tenants must never see each other's data, whatever IDs a
caller supplies. (Delegated MSSP access is covered in test_mssp.py.)
"""
from __future__ import annotations

import pytest

from astrasoc.db import SessionLocal
from astrasoc.models import Tenant
from astrasoc.services.tenants import create_user, provision_tenant

EMAIL = "manager@isolated.example"
PASSWORD = "Isolated!Pass123"


@pytest.fixture(scope="module")
def other_tenant(client):
    with SessionLocal() as db:
        if db.query(Tenant).filter(Tenant.slug == "isolated").first() is None:
            t = provision_tenant(db, name="Isolated Co", slug="isolated", kind="customer")
            create_user(db, t, email=EMAIL, full_name="Iso Manager", password=PASSWORD,
                        roles=["soc_manager"])
            db.commit()
    r = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_other_tenant_sees_none_of_acmes_incidents(client, manager, other_tenant):
    assert client.get("/api/v1/incidents", headers=manager).json()["total"] >= 1
    assert client.get("/api/v1/incidents", headers=other_tenant).json()["items"] == []


def test_other_tenant_cannot_fetch_acme_incident_by_id(client, manager, other_tenant):
    target = client.get("/api/v1/incidents", headers=manager).json()["items"][0]["id"]
    assert client.get(f"/api/v1/incidents/{target}", headers=manager).status_code == 200
    assert client.get(f"/api/v1/incidents/{target}", headers=other_tenant).status_code == 404


def test_customer_cannot_switch_into_peer_tenant(client, other_tenant):
    r = client.get("/api/v1/incidents", headers={**other_tenant, "X-Tenant-ID": "acme"})
    assert r.status_code == 403
    assert r.json()["error"] == "tenant_access_denied"
