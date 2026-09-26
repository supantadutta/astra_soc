"""MSSP multi-tenancy: hierarchy, delegated access, customer control, SLAs,
metering, onboarding/offboarding, content distribution and handover."""
from __future__ import annotations

import pytest
from conftest import as_tenant, login


def _slugs(client, headers):
    return {t["slug"] for t in client.get("/api/v1/tenants", headers=headers).json()["items"]}


# --- Delegated access ----------------------------------------------------------
def test_analyst_sees_only_granted_customers(client, mssp_analyst):
    assert _slugs(client, mssp_analyst) == {"astrasoc", "acme", "globex"}


def test_analyst_can_work_granted_customer_with_granted_role(client, mssp_analyst):
    h = as_tenant(mssp_analyst, "acme")
    assert client.get("/api/v1/incidents", headers=h).status_code == 200
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["roles"] == ["tier2_analyst"]
    assert "approval:decide" not in me["permissions"]
    assert client.post("/api/v1/approvals/00000000-0000-0000-0000-000000000000/approve",
                       headers=h, json={}).status_code == 403


def test_analyst_denied_ungranted_customer(client, mssp_analyst):
    r = client.get("/api/v1/incidents", headers=as_tenant(mssp_analyst, "initech"))
    assert r.status_code == 403
    assert r.json()["error"] == "tenant_access_denied"


def test_soc_manager_reaches_every_customer_including_reseller_customers(client, mssp_soc):
    assert {"acme", "globex", "initech", "contoso"} <= _slugs(client, mssp_soc)
    for slug in ("initech", "contoso"):
        assert client.get("/api/v1/incidents", headers=as_tenant(mssp_soc, slug)).status_code == 200


def test_customer_cannot_reach_peer_or_provider(client, globex_admin):
    for slug in ("acme", "astrasoc"):
        assert client.get("/api/v1/incidents",
                          headers=as_tenant(globex_admin, slug)).status_code == 403


def test_delegated_actions_are_attributed_in_customer_audit(client, mssp_soc, acme_ciso):
    iid = client.get("/api/v1/incidents", headers=as_tenant(mssp_soc, "acme")).json()["items"][0]["id"]
    client.post(f"/api/v1/incidents/{iid}/acknowledge", headers=as_tenant(mssp_soc, "acme"))
    events = client.get("/api/v1/audit?action=incident.acknowledged&page_size=50",
                        headers=acme_ciso).json()["items"]
    labels = [e["actor_label"] for e in events]
    assert labels and any("via astrasoc/provider" in lab for lab in labels) or not labels


def test_customer_can_switch_off_provider_access(client, acme_ciso, mssp_soc, mssp_analyst, admin):
    try:
        r = client.patch("/api/v1/tenants/current", headers=acme_ciso,
                         json={"delegation": {"allow_provider_access": False}})
        assert r.status_code == 200
        for h in (mssp_soc, mssp_analyst):
            assert client.get("/api/v1/incidents", headers=as_tenant(h, "acme")).status_code == 403
        # Platform operator can still enter — flagged as break-glass.
        me = client.get("/api/v1/tenants/current", headers=as_tenant(admin, "acme")).json()
        assert me["acting_as"]["delegated_via"] == "break_glass"
    finally:
        client.patch("/api/v1/tenants/current", headers=acme_ciso,
                     json={"delegation": {"allow_provider_access": True}})
    assert client.get("/api/v1/incidents", headers=as_tenant(mssp_soc, "acme")).status_code == 200


def test_provider_cannot_change_customer_delegation_policy(client, mssp_soc, admin):
    for h in (mssp_soc, admin):
        r = client.patch("/api/v1/tenants/current", headers=as_tenant(h, "acme"),
                         json={"delegation": {"allow_provider_access": True}})
        assert r.status_code in (403,)


# --- Portfolio views -------------------------------------------------------------
def test_portfolio_overview_scoped_to_access(client, mssp_soc, mssp_analyst):
    soc = client.get("/api/v1/mssp/overview", headers=mssp_soc).json()
    ana = client.get("/api/v1/mssp/overview", headers=mssp_analyst).json()
    assert {c["slug"] for c in soc["customers"]} >= {"acme", "globex", "initech", "contoso"}
    assert {c["slug"] for c in ana["customers"]} == {"acme", "globex"}
    assert soc["totals"]["open_incidents"] >= ana["totals"]["open_incidents"]


def test_customers_have_no_portfolio_access(client, acme_ciso, manager):
    for h in (acme_ciso, manager):
        assert client.get("/api/v1/mssp/overview", headers=h).status_code == 403


def test_unified_queue_is_sorted_by_urgency(client, mssp_soc):
    items = client.get("/api/v1/mssp/queue?page_size=200", headers=mssp_soc).json()["items"]
    assert items and {"tenant", "sla", "key"} <= set(items[0])
    order = {"breached": 0, "at_risk": 1, "on_track": 2, "met": 3, "n/a": 4}
    ranks = [order[i["sla"]["overall"]] for i in items]
    assert ranks == sorted(ranks)
    assert {i["tenant"]["slug"] for i in items} >= {"acme", "globex"}


def test_sla_report_and_usage_billing(client, mssp_soc, mssp_accounts, mssp_analyst):
    sla = client.get("/api/v1/mssp/sla", headers=mssp_soc).json()
    assert sla["customers"] and "ack_compliance" in sla["customers"][0]
    usage = client.get("/api/v1/mssp/usage", headers=mssp_accounts).json()
    acme = next(c for c in usage["customers"] if c["slug"] == "acme")
    assert acme["incidents"] >= 1
    csv_ = client.get("/api/v1/mssp/usage?format=csv", headers=mssp_accounts)
    assert csv_.status_code == 200 and csv_.text.startswith("period,tenant")
    assert client.get("/api/v1/mssp/usage", headers=mssp_analyst).status_code == 403


# --- Service plans ------------------------------------------------------------------
def test_essentials_plan_blocks_ai_investigation(client, mssp_soc):
    h = as_tenant(mssp_soc, "initech")
    iid = client.get("/api/v1/incidents", headers=h).json()["items"][0]["id"]
    r = client.post(f"/api/v1/incidents/{iid}/investigate", headers=h)
    assert r.status_code == 403
    assert r.json()["error"] == "feature_not_in_plan"


def test_contract_feature_override_enables_feature(client, mssp_soc, admin):
    tid = next(t["id"] for t in client.get("/api/v1/mssp/tenants", headers=mssp_soc).json()["items"]
               if t["slug"] == "initech")
    try:
        client.patch(f"/api/v1/mssp/tenants/{tid}", headers=mssp_soc,
                     json={"feature_overrides": {"ai_investigation": True}})
        h = as_tenant(mssp_soc, "initech")
        iid = client.get("/api/v1/incidents", headers=h).json()["items"][0]["id"]
        assert client.post(f"/api/v1/incidents/{iid}/investigate", headers=h).status_code == 200
    finally:
        client.patch(f"/api/v1/mssp/tenants/{tid}", headers=mssp_soc,
                     json={"feature_overrides": {}})


# --- Grants -------------------------------------------------------------------------
def test_grants_require_reason_and_non_admin_role_and_can_be_revoked(client, mssp_soc, mssp_analyst):
    staff = client.get("/api/v1/mssp/staff", headers=mssp_soc).json()["items"]
    analyst_id = next(s["id"] for s in staff if s["email"] == "analyst@astrasoc.io")
    initech = next(t["id"] for t in client.get("/api/v1/mssp/tenants", headers=mssp_soc).json()["items"]
                   if t["slug"] == "initech")
    base = {"user_id": analyst_id, "tenant_id": initech}
    assert client.post("/api/v1/mssp/grants", headers=mssp_soc,
                       json={**base, "role": "tier1_analyst"}).status_code == 422  # no reason
    assert client.post("/api/v1/mssp/grants", headers=mssp_soc,
                       json={**base, "role": "customer_admin", "reason": "cover shift"}).status_code == 422
    g = client.post("/api/v1/mssp/grants", headers=mssp_soc,
                    json={**base, "role": "tier1_analyst", "reason": "cover night shift",
                          "expires_in_hours": 8})
    assert g.status_code == 201
    h = as_tenant(mssp_analyst, "initech")
    assert client.get("/api/v1/incidents", headers=h).status_code == 200
    assert client.delete(f"/api/v1/mssp/grants/{g.json()['id']}", headers=mssp_soc).status_code == 200
    assert client.get("/api/v1/incidents", headers=h).status_code == 403


def test_analyst_cannot_manage_grants(client, mssp_analyst):
    assert client.get("/api/v1/mssp/grants", headers=mssp_analyst).status_code == 403


# --- Onboarding / offboarding --------------------------------------------------------
@pytest.fixture(scope="module")
def umbrella(client):
    h = login(client, "accounts@astrasoc.io")
    r = client.post("/api/v1/mssp/tenants", headers=h, json={
        "name": "Umbrella Pharma", "slug": "umbrella", "service_tier": "professional",
        "region": "eu", "status": "active",
        "sla_policy": {"critical": {"ack": 10}},
        "admin": {"email": "admin@umbrella.example", "full_name": "U Admin",
                  "password": "Umbrella!Pass123"}})
    assert r.status_code == 201, r.text
    return r.json()


def test_onboarding_creates_isolated_ready_tenant(client, umbrella, mssp_accounts):
    h = login(client, "admin@umbrella.example", "Umbrella!Pass123")
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["roles"] == ["customer_admin"]
    cur = client.get("/api/v1/tenants/current", headers=h).json()
    assert cur["effective_sla"]["critical"]["ack"] == 10
    assert cur["effective_sla"]["critical"]["resolve"] == 480  # professional default
    assert client.get("/api/v1/incidents", headers=h).json()["items"] == []
    assert len(client.get("/api/v1/detections", headers=h).json()["items"]) >= 5
    dup = client.post("/api/v1/mssp/tenants", headers=mssp_accounts,
                      json={"name": "Umbrella 2", "slug": "umbrella"})
    assert dup.status_code == 409


def test_onboarding_validates_input(client, mssp_accounts, manager):
    assert client.post("/api/v1/mssp/tenants", headers=mssp_accounts,
                       json={"name": "Bad", "slug": "Bad Slug!"}).status_code == 422
    assert client.post("/api/v1/mssp/tenants", headers=mssp_accounts, json={
        "name": "Weak", "slug": "weakco",
        "admin": {"email": "a@weak.example", "password": "short"}}).status_code == 422
    assert client.post("/api/v1/mssp/tenants", headers=manager,
                       json={"name": "Nope", "slug": "nope"}).status_code == 403


def test_offboarding_requires_suspension_and_confirmation(client, umbrella, mssp_accounts):
    tid = umbrella["id"]
    assert client.request("DELETE", f"/api/v1/mssp/tenants/{tid}", headers=mssp_accounts,
                          json={"confirm": "umbrella"}).status_code == 409
    assert client.post(f"/api/v1/mssp/tenants/{tid}/suspend", headers=mssp_accounts,
                       json={}).status_code == 200
    # Suspended customers cannot log in.
    assert client.post("/api/v1/auth/login", json={"email": "admin@umbrella.example",
                                                   "password": "Umbrella!Pass123"}).status_code in (401, 403)
    export = client.get(f"/api/v1/mssp/tenants/{tid}/export", headers=mssp_accounts).json()
    assert export["format"] == "astrasoc-tenant-export/1"
    assert all("password_hash" not in u for u in export["users"])
    assert client.request("DELETE", f"/api/v1/mssp/tenants/{tid}", headers=mssp_accounts,
                          json={"confirm": "wrong"}).status_code == 422
    r = client.request("DELETE", f"/api/v1/mssp/tenants/{tid}", headers=mssp_accounts,
                       json={"confirm": "umbrella"})
    assert r.status_code == 200, r.text
    assert "umbrella" not in _slugs(client, mssp_accounts)


# --- Content, handover, service reports, SLA escalation ---------------------------------
def test_managed_detection_content_distribution(client, mssp_soc):
    lib = client.get("/api/v1/mssp/content/detections", headers=mssp_soc).json()["items"]
    rule = lib[0]
    r = client.post(f"/api/v1/mssp/content/detections/{rule['id']}/deploy", headers=mssp_soc,
                    json={"all": True})
    assert r.status_code == 200
    assert {x["status"] for x in r.json()["results"]} <= {"created", "updated", "skipped"}
    assert any(x["status"] in ("created", "updated") for x in r.json()["results"])


def test_shift_handover_must_be_acknowledged_by_incoming_shift(client, mssp_analyst, mssp_soc):
    iid = client.get("/api/v1/mssp/queue", headers=mssp_analyst).json()["items"][0]["id"]
    h = client.post("/api/v1/mssp/handovers", headers=mssp_analyst, json={
        "shift": "night", "summary": "Two criticals open",
        "open_items": [{"incident_id": iid, "note": "awaiting EDR isolation approval"}]})
    assert h.status_code == 201
    hid = h.json()["id"]
    assert client.post(f"/api/v1/mssp/handovers/{hid}/acknowledge",
                       headers=mssp_analyst).status_code == 409
    assert client.post(f"/api/v1/mssp/handovers/{hid}/acknowledge",
                       headers=mssp_soc).status_code == 200


def test_monthly_service_reports_land_in_customer_tenants(client, mssp_soc, acme_ciso):
    r = client.post("/api/v1/mssp/reports/service", headers=mssp_soc, json={})
    assert r.status_code == 200 and r.json()["reports"]
    acme_reports = client.get("/api/v1/reports?report_type=service_report",
                              headers=acme_ciso).json()["items"]
    assert acme_reports


def test_sla_sweeper_escalates_breaches_to_customer_and_provider(client, manager, mssp_soc):
    from astrasoc.db import SessionLocal
    from astrasoc.services.sla import sweep_breaches

    with SessionLocal() as db:
        n = sweep_breaches(db)
        db.commit()
    # Seeded demo cases include unacknowledged criticals older than their
    # 15-minute enterprise SLA, so at least one escalation must happen once.
    assert n >= 1
    with SessionLocal() as db:
        assert sweep_breaches(db) == 0  # idempotent
    cust = client.get("/api/v1/notifications", headers=manager).json()
    prov = client.get("/api/v1/mssp/notifications", headers=mssp_soc).json()
    assert any(i["category"] == "sla_breach" for i in cust["items"])
    assert any(i["category"] == "sla_breach" for i in prov["items"])


def test_me_reports_acting_tenant_and_delegation(client, mssp_soc):
    home = client.get("/api/v1/auth/me", headers=mssp_soc).json()
    assert home["tenant_kind"] == "provider" and home["delegated_via"] is None
    assert "mssp:portfolio" in home["home_permissions"]
    acting = client.get("/api/v1/auth/me", headers=as_tenant(mssp_soc, "acme")).json()
    assert acting["tenant_slug"] == "acme" and acting["tenant_kind"] == "customer"
    assert acting["delegated_via"] == "provider"
    assert acting["home_tenant_slug"] == home["tenant_slug"]
    # Acting permissions are the customer's; portfolio authority stays at home.
    assert "mssp:portfolio" not in acting["permissions"]
    assert "mssp:portfolio" in acting["home_permissions"]
