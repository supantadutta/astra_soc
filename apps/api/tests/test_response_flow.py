"""End-to-end governed response: create -> policy -> approval -> execute -> verify -> rollback."""


def _ransomware_incident(client, headers):
    incs = client.get("/api/v1/incidents?scenario=ransomware_precursor", headers=headers).json()["items"]
    return incs[0]["id"]


def _confirmed_fact(client, headers, iid):
    d = client.get(f"/api/v1/incidents/{iid}", headers=headers).json()
    return d["evidence_by_kind"]["confirmed_fact"][0]["id"]


def test_full_response_pipeline(client, manager, commander):
    iid = _ransomware_incident(client, manager)
    fact = _confirmed_fact(client, manager, iid)

    # Request isolate on a critical asset -> requires approval.
    r = client.post("/api/v1/response/actions", headers=manager, json={
        "action_type": "isolate_endpoint", "target": {"value": "FIN-WKS-014"},
        "incident_id": iid, "evidence_ids": [fact], "confidence": 0.86,
        "expected_outcome": "contain",
    })
    assert r.status_code == 200, r.text
    action = r.json()["action"]
    assert action["status"] == "pending_approval"
    aid = action["id"]

    # Cannot execute before approval.
    assert client.post(f"/api/v1/response/actions/{aid}/execute", headers=manager).status_code == 400

    # Approve as commander.
    appr = [a for a in client.get("/api/v1/approvals?status=pending", headers=commander).json()["items"]
            if a["response_action_id"] == aid][0]
    assert client.post(f"/api/v1/approvals/{appr['id']}/approve", headers=commander,
                       json={"note": "ok"}).status_code == 200

    # Execute -> simulated in demo, then auto-verified.
    r = client.post(f"/api/v1/response/actions/{aid}/execute", headers=manager)
    assert r.status_code == 200
    assert r.json()["status"] == "verified"
    assert r.json()["simulated"] is True

    # Rollback.
    r = client.post(f"/api/v1/response/actions/{aid}/rollback", headers=manager)
    assert r.json()["status"] == "rolled_back"


def test_action_without_confirmed_fact_rejected(client, manager):
    iid = _ransomware_incident(client, manager)
    r = client.post("/api/v1/response/actions", headers=manager, json={
        "action_type": "disable_account", "target": {"value": "someone"},
        "incident_id": iid, "evidence_ids": [], "confidence": 0.9,
    })
    assert r.status_code == 400
    assert r.json()["error"] == "insufficient_evidence"


def test_alert_promotes_to_incident(client, manager):
    alerts = client.get("/api/v1/alerts?status=new", headers=manager).json()["items"]
    new = next((a for a in alerts if not a["incident_id"]), None)
    if new is None:
        return  # no free alert this run; skip silently
    r = client.post(f"/api/v1/alerts/{new['id']}/promote", headers=manager)
    assert r.status_code == 200
    assert r.json()["key"].startswith("INC-")
