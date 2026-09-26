"""Workflow engine durability/semantics, query engine, detection lifecycle,
tenant-scoped demo reset and honest evaluation metrics."""
from __future__ import annotations

from conftest import as_tenant, login
from sqlalchemy import func, select


def _incident(client, headers, scenario="ransomware_precursor"):
    return client.get(f"/api/v1/incidents?scenario={scenario}", headers=headers).json()["items"][0]


# --- Workflows ---------------------------------------------------------------------
def test_workflow_history_persists_and_approval_gate_is_enforced(client, manager, tier1, commander):
    inc = _incident(client, manager)
    client.patch(f"/api/v1/incidents/{inc['id']}", headers=manager, json={"confidence": 0.9})
    run = client.post("/api/v1/playbooks/pb_ransomware_containment/run", headers=manager,
                      json={"incident_id": inc["id"]}).json()
    assert run["status"] == "waiting_approval"
    persisted = client.get(f"/api/v1/playbooks/runs/{run['id']}", headers=manager).json()
    # Every step before the approval gate is persisted, not just the first.
    assert [h["id"] for h in persisted["step_history"]] == ["s1", "s2", "s3", "s4", "s5"]

    # tier-1 lacks approval:decide
    assert client.post(f"/api/v1/playbooks/runs/{run['id']}/resume", headers=tier1,
                       json={}).status_code == 403
    res = client.post(f"/api/v1/playbooks/runs/{run['id']}/resume", headers=commander,
                      json={"decision": "approve", "note": "go"})
    assert res.status_code == 200, res.text
    body = res.json()
    ids = [h["id"] for h in body["step_history"]]
    assert ids.count("s2") == 1 and ids.count("s3") == 1  # completed steps never re-run
    assert body["status"] in ("completed", "failed")
    if body["status"] == "failed":
        assert body["error"]  # failures are reported, never hidden as completed


def test_condition_false_ends_run_and_skips_remaining(client, manager):
    inc = _incident(client, manager, "insider_risk")
    client.patch(f"/api/v1/incidents/{inc['id']}", headers=manager, json={"confidence": 0.3})
    run = client.post("/api/v1/playbooks/pb_ransomware_containment/run", headers=manager,
                      json={"incident_id": inc["id"]}).json()
    assert run["status"] == "completed"
    assert run["context"]["outcome"] == "condition_not_met"
    assert any(h["status"] == "skipped" for h in run["step_history"])


def test_tier1_cannot_run_playbooks_and_unknown_playbook_is_404(client, tier1, manager):
    assert client.post("/api/v1/playbooks/pb_generic_enrich/run", headers=tier1,
                       json={}).status_code == 403
    assert client.post("/api/v1/playbooks/does_not_exist/run", headers=manager,
                       json={}).status_code == 404


def test_idempotency_keys_are_tenant_scoped(client, manager, mssp_soc):
    a = client.post("/api/v1/playbooks/pb_generic_enrich/run", headers=manager,
                    json={"idempotency_key": "shared-key-1"}).json()
    again = client.post("/api/v1/playbooks/pb_generic_enrich/run", headers=manager,
                        json={"idempotency_key": "shared-key-1"}).json()
    assert again["id"] == a["id"]
    other = client.post("/api/v1/playbooks/pb_generic_enrich/run",
                        headers=as_tenant(mssp_soc, "globex"),
                        json={"idempotency_key": "shared-key-1"}).json()
    assert other["id"] != a["id"]


def test_invalid_playbook_graph_rejected(client, manager):
    r = client.put("/api/v1/playbooks/pb_bad_graph", headers=manager,
                   json={"name": "bad", "graph": {"steps": [{"id": "x", "type": "teleport"}]}})
    assert r.status_code == 422


# --- Query engine ------------------------------------------------------------------
def test_query_filters_are_actually_applied(client, manager):
    host = client.get("/api/v1/incidents?scenario=ransomware_precursor",
                      headers=manager).json()["items"][0]["affected_hosts"][0]
    hit = client.post("/api/v1/query/execute", headers=manager,
                      json={"query": f'search host="{host}"', "language": "spl"}).json()
    miss = client.post("/api/v1/query/execute", headers=manager,
                       json={"query": 'search host="NO-SUCH-HOST"', "language": "spl"}).json()
    assert hit["row_count"] >= 1 and all(r["host"] == host for r in hit["results"])
    assert miss["row_count"] == 0
    assert hit["applied_filters"] == [{"field": "host_name", "op": "eq", "value": host}]


def test_query_reports_unsupported_terms(client, manager):
    r = client.post("/api/v1/query/execute", headers=manager,
                    json={"query": "process_name=evil.exe", "language": "kql"}).json()
    assert r["unsupported_terms"] and "not applied" in r["note"]


def test_query_blocked_by_plan(client, mssp_soc):
    r = client.post("/api/v1/query/execute", headers=as_tenant(mssp_soc, "initech"),
                    json={"query": "host=x"})
    assert r.status_code == 403 and r.json()["error"] == "feature_not_in_plan"


# --- Detection lifecycle -----------------------------------------------------------
RULE = {"name": "Test rule", "severity": "high",
        "matcher": {"all": [{"field": "activity", "op": "eq", "value": "Process create"}]}}


def test_detection_rule_four_eyes_and_reapproval(client):
    hunter = login(client, "hunter@acme.io")
    deteng = login(client, "deteng@acme.io")
    rid = client.post("/api/v1/detections", headers=deteng, json=RULE).json()["id"]
    # author cannot approve own rule
    assert client.patch(f"/api/v1/detections/{rid}", headers=deteng,
                        json={"status": "approved"}).status_code == 403
    # cannot deploy before approval
    mgr = login(client, "manager@acme.io")
    assert client.patch(f"/api/v1/detections/{rid}", headers=mgr,
                        json={"status": "deployed"}).status_code == 409
    assert client.patch(f"/api/v1/detections/{rid}", headers=mgr,
                        json={"status": "approved"}).status_code == 200
    assert client.patch(f"/api/v1/detections/{rid}", headers=mgr,
                        json={"status": "deployed"}).json()["enabled"] is True
    # changing logic after deployment forces re-review
    r = client.patch(f"/api/v1/detections/{rid}", headers=hunter,
                     json={"matcher": {"field": "activity", "op": "contains", "value": "x"}}).json()
    assert r["status"] == "review" and r["enabled"] is False and r["approved_by"] is None


def test_invalid_matcher_rejected(client, manager):
    bad = {**RULE, "matcher": {"field": "a", "op": "regex", "value": "("}}
    assert client.post("/api/v1/detections", headers=manager, json=bad).status_code == 422
    bad = {**RULE, "matcher": {"field": "a", "op": "eval"}}
    assert client.post("/api/v1/detections", headers=manager, json=bad).status_code == 422


def test_managed_rules_locked_for_customer(client, manager):
    rules = client.get("/api/v1/detections?page_size=200", headers=manager).json()["items"]
    managed = next(r for r in rules if (r["deployment_target"] or "").startswith("managed:"))
    assert client.patch(f"/api/v1/detections/{managed['id']}", headers=manager,
                        json={"matcher": RULE["matcher"]}).status_code == 409
    assert client.patch(f"/api/v1/detections/{managed['id']}", headers=manager,
                        json={"exceptions": [{"host": "BACKUP-01"}]}).status_code == 200


def test_replay_reports_no_precision_without_labels(client, manager):
    rules = client.get("/api/v1/detections?page_size=200", headers=manager).json()["items"]
    r = client.post(f"/api/v1/detections/{rules[0]['id']}/replay", headers=manager).json()
    assert r["precision"] is None and r["recall"] is None and r["labelled"] is False


# --- Demo reset scope --------------------------------------------------------------
def test_demo_reset_only_touches_own_tenant(client, mssp_soc):
    from astrasoc.db import SessionLocal
    from astrasoc.models import Incident, IncidentAlert, Tenant

    def links(slug):
        with SessionLocal() as db:
            tid = db.execute(select(Tenant.id).where(Tenant.slug == slug)).scalar_one()
            return db.execute(select(func.count()).select_from(IncidentAlert).join(
                Incident, IncidentAlert.incident_id == Incident.id).where(
                Incident.tenant_id == tid)).scalar()

    before = links("acme")
    assert before > 0
    r = client.post("/api/v1/demo/reset", headers=as_tenant(mssp_soc, "globex"))
    assert r.status_code == 200, r.text
    assert links("acme") == before


# --- Evaluations -----------------------------------------------------------------------
def test_evaluation_refuses_unautomated_stages(client, manager):
    ds = client.post("/api/v1/learning/datasets/build", headers=manager, json={}).json()
    r = client.post("/api/v1/learning/runs", headers=manager,
                    json={"dataset_id": ds["id"], "stage": "canary"})
    assert r.status_code == 422
    run = client.post("/api/v1/learning/runs", headers=manager,
                      json={"dataset_id": ds["id"]}).json()
    assert run["metrics"]["method"].startswith("analyst-agreement")
