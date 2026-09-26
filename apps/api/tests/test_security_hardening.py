"""Regression tests for the security review findings.

Each test pins down a control that must hold server-side regardless of what
the client sends.
"""
from __future__ import annotations

from conftest import login


def _slack(client, headers):
    return next(c for c in client.get("/api/v1/connectors", headers=headers).json()["items"]
                if c["kind"] == "slack")


# --- Secret references & egress ----------------------------------------------
def test_env_and_file_secret_refs_rejected(client, manager):
    c = _slack(client, manager)
    for ref in ("env://ASTRASOC_JWT_SECRET", "file:///etc/passwd"):
        r = client.patch(f"/api/v1/connectors/{c['id']}", headers=manager,
                         json={"credential_refs": [{"field": "api_token", "secret_ref": ref}]})
        assert r.status_code == 422, ref
        assert r.json()["error"] == "invalid_secret_ref"


def test_tenant_secret_refs_confined_to_own_namespace(client, manager):
    c = _slack(client, manager)
    bad = client.patch(f"/api/v1/connectors/{c['id']}", headers=manager, json={
        "credential_refs": [{"field": "api_token", "secret_ref": "vault://tenants/globex/slack#t"}]})
    assert bad.status_code == 422
    ok = client.patch(f"/api/v1/connectors/{c['id']}", headers=manager, json={
        "credential_refs": [{"field": "api_token", "secret_ref": "vault://tenants/acme/slack#t"}]})
    assert ok.status_code == 200


def test_egress_policy_blocks_metadata_and_loopback(client, manager):
    c = _slack(client, manager)
    for url in ("http://169.254.169.254/latest", "http://metadata.google.internal/",
                "http://127.0.0.1:8000", "http://localhost:9000", "ftp://example.com"):
        r = client.patch(f"/api/v1/connectors/{c['id']}", headers=manager, json={"base_url": url})
        assert r.status_code == 422, url
        assert r.json()["error"] == "egress_blocked"


def test_unsafe_secret_scheme_never_resolves():
    from astrasoc.services.secrets import resolve_secret

    assert resolve_secret("env://ASTRASOC_JWT_SECRET") is None


# --- RBAC grant rules ------------------------------------------------------------
def test_cannot_create_wildcard_or_unheld_permission_roles(client, manager):
    for perms in (["*"], ["platform:admin"], ["user:manage"], ["mssp:portfolio"], ["bogus:perm"]):
        r = client.post("/api/v1/rbac/roles", headers=manager,
                        json={"name": f"r_{abs(hash(tuple(perms))) % 10**6}", "permissions": perms})
        assert r.status_code == 403, perms
    ok = client.post("/api/v1/rbac/roles", headers=manager,
                     json={"name": "night_triage", "permissions": ["alert:read", "alert:write"]})
    assert ok.status_code == 200


def test_cannot_assign_role_exceeding_own_permissions(client, manager):
    me = client.get("/api/v1/auth/me", headers=manager).json()
    r = client.post(f"/api/v1/rbac/users/{me['id']}/roles", headers=manager,
                    json={"role": "tenant_admin"})
    assert r.status_code == 403


def test_tenant_list_is_scoped_to_accessible_tenants(client, manager):
    slugs = {t["slug"] for t in client.get("/api/v1/tenants", headers=manager).json()["items"]}
    assert slugs == {"acme"}


def test_agent_registry_is_platform_only(client, manager, admin):
    assert client.patch("/api/v1/agents/triage_agent", headers=manager,
                        json={"enabled": True}).status_code == 403
    assert client.patch("/api/v1/agents/triage_agent", headers=admin,
                        json={"enabled": True}).status_code == 200


def test_global_knowledge_is_platform_only(client, manager):
    r = client.post("/api/v1/knowledge/documents", headers=manager,
                    json={"title": "x", "body": "y", "scope": "global_knowledge"})
    assert r.status_code == 403


# --- Sessions, refresh rotation, lockout, API keys ---------------------------------
def test_logout_revokes_access_token(client):
    h = login(client, "t1@acme.io")
    assert client.get("/api/v1/auth/me", headers=h).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_refresh_rotates_and_detects_reuse(client):
    r = client.post("/api/v1/auth/login", json={"email": "exec@acme.io", "password": "Demo!Pass123"})
    first = r.json()
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r2.status_code == 200
    rotated = r2.json()
    assert rotated["refresh_token"] != first["refresh_token"]
    # Replaying the superseded token revokes the whole session.
    assert client.post("/api/v1/auth/refresh",
                       json={"refresh_token": first["refresh_token"]}).status_code == 401
    h = {"Authorization": f"Bearer {rotated['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_account_lockout_after_repeated_failures(client, admin):
    client.post("/api/v1/rbac/users", headers=admin, json={
        "email": "lockme@astrasoc.io", "full_name": "Lock", "password": "Lock!Pass12345",
        "roles": ["auditor"]})
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": "lockme@astrasoc.io", "password": "nope"})
    r = client.post("/api/v1/auth/login", json={"email": "lockme@astrasoc.io",
                                                "password": "Lock!Pass12345"})
    assert r.status_code == 401  # locked even with the right password


def test_weak_password_rejected_on_user_creation(client, admin):
    r = client.post("/api/v1/rbac/users", headers=admin, json={
        "email": "weak@astrasoc.io", "password": "password", "roles": ["auditor"]})
    assert r.status_code == 422


def test_api_keys_need_scopes_and_cannot_exceed_creator(client, admin):
    assert client.post("/api/v1/auth/api-keys", headers=admin,
                       json={"name": "noscopes", "scopes": []}).status_code == 422
    r = client.post("/api/v1/auth/api-keys", headers=admin,
                    json={"name": "reader", "scopes": ["incident:read"]})
    assert r.status_code == 201
    key = r.json()["api_key"]
    me = client.get("/api/v1/auth/me", headers={"X-API-Key": key}).json()
    assert me["permissions"] == ["incident:read"]
    assert client.get("/api/v1/audit", headers={"X-API-Key": key}).status_code == 403


def test_mode_endpoint_requires_auth(client):
    assert client.get("/api/v1/mode").status_code == 401


# --- Evidence integrity -------------------------------------------------------------
def _ransomware(client, headers):
    return client.get("/api/v1/incidents?scenario=ransomware_precursor",
                      headers=headers).json()["items"][0]["id"]


def test_analysts_cannot_mint_confirmed_facts(client, t2):
    iid = _ransomware(client, t2)
    r = client.post(f"/api/v1/incidents/{iid}/evidence", headers=t2,
                    json={"kind": "confirmed_fact", "title": "trust me"})
    assert r.status_code == 403
    for kind in ("model_inference", "executed_action", "anything"):
        assert client.post(f"/api/v1/incidents/{iid}/evidence", headers=t2,
                           json={"kind": kind, "title": "x"}).status_code == 422


def test_attested_fact_requires_source_ref(client, t3):
    iid = _ransomware(client, t3)
    r = client.post(f"/api/v1/incidents/{iid}/evidence", headers=t3,
                    json={"kind": "confirmed_fact", "title": "EDR telemetry"})
    assert r.status_code == 422
    r = client.post(f"/api/v1/incidents/{iid}/evidence", headers=t3,
                    json={"kind": "confirmed_fact", "title": "EDR telemetry",
                          "source_ref": "edr:event/88213"})
    assert r.status_code == 200
    assert r.json()["produced_by"].startswith("attested:")


# --- Reports never cross tenants --------------------------------------------------
def test_report_rejects_foreign_incident(client, manager, globex_admin):
    iid = _ransomware(client, manager)
    r = client.post("/api/v1/reports", headers=globex_admin,
                    json={"report_type": "incident", "incident_id": iid})
    assert r.status_code == 404


def test_html_export_escapes_content(client, t3, manager):
    iid = _ransomware(client, t3)
    client.post(f"/api/v1/incidents/{iid}/notes", headers=t3, json={"note": "x"})
    client.patch(f"/api/v1/incidents/{iid}", headers=manager,
                 json={"summary": "<script>alert(1)</script>"})
    rep = client.post("/api/v1/reports", headers=manager,
                      json={"report_type": "incident", "incident_id": iid}).json()
    body = client.get(f"/api/v1/reports/{rep['id']}/export?format=html", headers=manager).text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


# --- Production guard & HTTP hardening ------------------------------------------
def test_production_guard_rejects_unsafe_configuration():
    from astrasoc.config import Settings, production_problems

    weak = Settings(environment="production", jwt_secret="change-me", database_url="sqlite:///x.db",
                    cors_origins="*")
    problems = " ".join(production_problems(weak))
    for needle in ("JWT_SECRET", "AUDIT_KEY", "SQLite", "CORS"):
        assert needle in problems
    strong = Settings(environment="production", jwt_secret="x" * 20 + "Qz9#" + "y" * 20,
                      audit_key="a" * 20 + "Kp2!" + "b" * 20,
                      database_url="postgresql+psycopg2://u@h/db", cors_origins="https://soc.example.com")
    assert production_problems(strong) == []


def test_production_never_seeds_demo_users():
    from astrasoc.config import Settings

    assert Settings(environment="production").should_seed_demo_users is False
    assert Settings(environment="demo").should_seed_demo_users is True


def test_security_headers_present(client, manager):
    r = client.get("/api/v1/incidents", headers=manager)
    for h in ("x-content-type-options", "x-frame-options", "content-security-policy",
              "referrer-policy", "cache-control", "x-request-id"):
        assert h in r.headers, h
    assert r.headers["cache-control"] == "no-store"


def test_oversized_body_rejected(client, manager):
    r = client.post("/api/v1/incidents/x/notes", headers={**manager, "content-length": str(6 * 1024 * 1024)},
                    content=b"{}")
    assert r.status_code == 413


def test_internal_domain_accounts_can_sign_in(client, admin):
    """Login and account creation must agree on what an email is."""
    r = client.post("/api/v1/rbac/users", headers=admin, json={
        "email": "SOC.Lead@corp.local", "full_name": "Lead", "password": "Internal!Pass123",
        "roles": ["auditor"]})
    assert r.status_code == 200, r.text
    ok = client.post("/api/v1/auth/login", json={"email": "soc.lead@corp.local",
                                                  "password": "Internal!Pass123"})
    assert ok.status_code == 200
    bad = client.post("/api/v1/rbac/users", headers=admin, json={
        "email": "not-an-email", "password": "Internal!Pass123", "roles": ["auditor"]})
    assert bad.status_code == 422


def test_login_options_only_advertise_demo_accounts_when_seeded(client, monkeypatch):
    from astrasoc.config import settings

    assert client.get("/api/v1/auth/login-options").json()["demo_accounts"] is True  # test env
    monkeypatch.setattr(settings, "seed_demo_users", False)
    assert client.get("/api/v1/auth/login-options").json()["demo_accounts"] is False


def test_rate_limit_is_per_credential_not_shared_proxy_ip():
    """Users behind one NAT/reverse proxy must not throttle each other."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from astrasoc.middleware import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, per_minute=3)

    @app.get("/api/v1/ping")
    def ping():
        return {"ok": True}

    c = TestClient(app)
    alice, bob = {"Authorization": "Bearer alice"}, {"Authorization": "Bearer bob"}
    assert [c.get("/api/v1/ping", headers=alice).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert c.get("/api/v1/ping", headers=bob).status_code == 200
    # Browser sessions (cookie, no Authorization header) get their own budgets too.
    carol, dave = TestClient(app, cookies={"astrasoc_at": "carol"}), TestClient(app, cookies={"astrasoc_at": "dave"})
    assert [carol.get("/api/v1/ping").status_code for _ in range(4)] == [200, 200, 200, 429]
    assert dave.get("/api/v1/ping").status_code == 200
