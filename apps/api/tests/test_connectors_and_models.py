"""Connector + provider health tests report the truth (no fake success)."""


def test_provider_test_simulated_healthy(client, admin):
    p = client.get("/api/v1/models/providers", headers=admin).json()["items"][0]
    r = client.post(f"/api/v1/models/providers/{p['id']}/test", headers=admin)
    assert r.json()["state"] == "healthy"


def test_real_provider_without_secret_is_not_configured(client, admin):
    created = client.post("/api/v1/models/providers", headers=admin, json={
        "kind": "openai", "name": "OpenAI (test)", "base_url": "https://api.openai.com",
    }).json()
    r = client.post(f"/api/v1/models/providers/{created['id']}/test", headers=admin)
    # Honest: cannot claim healthy without a credential.
    assert r.json()["state"] == "not_configured"


def test_connector_mock_test_labeled_mock(client, admin):
    c = client.get("/api/v1/connectors", headers=admin).json()["items"][0]
    r = client.post(f"/api/v1/connectors/{c['id']}/test", headers=admin)
    assert r.json()["state"] == "healthy"
    assert r.json()["mock"] is True


def test_query_rejects_destructive(client, manager):
    r = client.post("/api/v1/query/execute", headers=manager,
                    json={"query": "DELETE FROM events", "language": "sql"})
    assert r.status_code == 400
    assert r.json()["error"] == "destructive_query"


def test_report_export_pdf(client, manager):
    r = client.post("/api/v1/reports", headers=manager, json={"report_type": "executive_summary"})
    rid = r.json()["id"]
    pdf = client.get(f"/api/v1/reports/{rid}/export?format=pdf", headers=manager)
    assert pdf.status_code == 200
    assert pdf.content[:5] == b"%PDF-"


def test_audit_chain_intact(client, auditor):
    assert client.get("/api/v1/audit/verify", headers=auditor).json()["verified"] is True
