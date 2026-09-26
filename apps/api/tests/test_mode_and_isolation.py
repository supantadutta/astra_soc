"""DEMO/LIVE mode enforcement and demo/live data separation."""


def test_default_mode_is_demo(client, manager):
    assert client.get("/api/v1/mode", headers=manager).json()["mode"] == "DEMO"


def test_live_switch_requires_confirmation_and_readiness(client, admin):
    # Without confirm -> 400.
    r = client.post("/api/v1/mode/switch", headers=admin, json={"mode": "LIVE"})
    assert r.status_code == 400
    # With confirm but failing readiness (no live connector) -> 400 readiness.
    r = client.post("/api/v1/mode/switch", headers=admin, json={"mode": "LIVE", "confirm": True})
    assert r.status_code == 400
    assert r.json()["error"] in ("readiness_failed", "confirmation_required")


def test_demo_data_present(client, manager):
    total = client.get("/api/v1/incidents", headers=manager).json()["total"]
    assert total >= 10  # seeded scenarios


def test_demo_scope_only_returns_demo_rows(client, manager):
    """Every incident the API returns in DEMO mode must be DEMO-scoped, and a
    LIVE-scoped row planted in the same tenant must never appear."""
    import uuid

    from astrasoc.db import SessionLocal
    from astrasoc.models import Incident, Tenant

    with SessionLocal() as db:
        acme = db.query(Tenant).filter(Tenant.slug == "acme").one()
        live = Incident(tenant_id=acme.id, data_scope="LIVE", key="INC-LIVE-1",
                        title=f"live-only {uuid.uuid4().hex[:6]}", severity="high")
        db.add(live)
        db.commit()
        live_id = str(live.id)
    items = client.get("/api/v1/incidents?page_size=200", headers=manager).json()["items"]
    assert items and all(i["data_scope"] == "DEMO" for i in items)
    assert live_id not in {i["id"] for i in items}
    assert client.get(f"/api/v1/incidents/{live_id}", headers=manager).status_code == 404
    assert client.get("/api/v1/system/summary", headers=manager).json()["scope"] == "DEMO"
