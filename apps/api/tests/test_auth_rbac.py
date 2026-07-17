"""Authentication and RBAC enforcement (server-side)."""


def test_login_and_me(client, manager):
    r = client.get("/api/v1/auth/me", headers=manager)
    assert r.status_code == 200
    assert "soc_manager" in r.json()["roles"]


def test_bad_credentials_rejected(client):
    r = client.post("/api/v1/auth/login", json={"email": "manager@acme.io", "password": "wrong"})
    assert r.status_code == 401


def test_unauthenticated_blocked(client):
    assert client.get("/api/v1/incidents").status_code == 401


def test_rbac_tier1_cannot_request_action(client, tier1):
    r = client.post("/api/v1/response/actions", headers=tier1,
                    json={"action_type": "isolate_endpoint", "target": {"value": "x"},
                          "confidence": 0.9})
    assert r.status_code == 403


def test_rbac_auditor_read_only(client, auditor):
    assert client.get("/api/v1/audit/verify", headers=auditor).status_code == 200
    # Auditor lacks mode:manage.
    assert client.post("/api/v1/mode/switch", headers=auditor,
                       json={"mode": "LIVE"}).status_code == 403


def test_rbac_manager_can_read_incidents(client, manager):
    assert client.get("/api/v1/incidents", headers=manager).status_code == 200
