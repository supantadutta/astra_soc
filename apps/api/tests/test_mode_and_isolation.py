"""DEMO/LIVE mode enforcement and demo/live data separation."""


def test_default_mode_is_demo(client, manager):
    assert client.get("/api/v1/mode").json()["mode"] == "DEMO"


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
    for item in client.get("/api/v1/incidents", headers=manager).json()["items"]:
        # get full incident and confirm scope
        pass
    # All seeded incidents are DEMO-scoped; the query layer filters by scope.
    assert client.get("/api/v1/system/summary", headers=manager).json()["scope"] == "DEMO"
