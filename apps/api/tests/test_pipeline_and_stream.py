"""Event bus isolation/delivery, stream tickets, and the ingestion →
detection → alert → correlation pipeline."""
from __future__ import annotations

import asyncio
import threading

from conftest import login


# --- Event bus ------------------------------------------------------------------
def test_bus_delivers_cross_thread_and_isolates_tenants():
    from astrasoc.services.events import Event, EventBus

    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        sub_a = bus.subscribe("tenant-a", "DEMO")
        sub_b = bus.subscribe("tenant-b", "DEMO")

        def worker():  # publishers usually run in worker threads
            bus.publish_soon(Event(type="x", scope="DEMO", tenant_id="tenant-a", data={"n": 1}))
            bus.publish_soon(Event(type="x", scope="LIVE", tenant_id="tenant-a", data={"n": 2}))
            bus.publish_soon(Event(type="x", scope="DEMO", tenant_id=None, data={"n": 3}))

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        got = await asyncio.wait_for(sub_a.queue.get(), timeout=2)
        assert got.data["n"] == 1
        await asyncio.sleep(0.05)
        assert sub_a.queue.empty()  # wrong scope + tenantless events never delivered
        assert sub_b.queue.empty()  # other tenant never sees it

    asyncio.run(scenario())


def test_stream_requires_valid_ticket_and_live_session(client):
    assert client.get("/api/v1/stream").status_code == 422
    assert client.get("/api/v1/stream?ticket=garbage").status_code == 401
    h = login(client, "auditor@acme.io")
    ticket = client.post("/api/v1/stream/ticket", headers=h).json()["ticket"]
    # an access token is not a stream ticket
    assert client.get(f"/api/v1/stream?ticket={h['Authorization'].split()[1]}").status_code == 401
    client.post("/api/v1/auth/logout", headers=h)
    assert client.get(f"/api/v1/stream?ticket={ticket}").status_code == 401


def test_stream_ticket_is_bound_to_acting_tenant(client, mssp_soc):
    t = client.post("/api/v1/stream/ticket", headers={**mssp_soc, "X-Tenant-ID": "globex"}).json()
    tenants = {x["slug"]: x["id"] for x in client.get("/api/v1/tenants", headers=mssp_soc).json()["items"]}
    assert t["tenant_id"] == tenants["globex"]


# --- Pipeline ---------------------------------------------------------------------
def _ingest_key(client, headers) -> dict:
    r = client.post("/api/v1/auth/api-keys", headers=headers,
                    json={"name": "forwarder", "scopes": ["event:ingest"]})
    assert r.status_code == 201, r.text
    return {"X-API-Key": r.json()["api_key"]}


def test_ingested_event_triggers_detection_and_correlated_incident(client, admin):
    ciso = login(client, "ciso@acme.io")
    # customer_admin cannot mint an ingest key (does not hold event:ingest)
    assert client.post("/api/v1/auth/api-keys", headers=ciso,
                       json={"name": "x", "scopes": ["event:ingest"]}).status_code == 403
    key = _ingest_key(client, {**admin, "X-Tenant-ID": "acme"})
    host = "PIPE-TEST-01"
    r = client.post("/api/v1/ingest/events", headers=key, json={"events": [
        {"activity": "Process create", "cmdline": "vssadmin.exe delete shadows /all /quiet",
         "host": host, "user": "acme\\pipeline", "source": "microsoft_defender"}]})
    assert r.status_code == 200, r.text
    assert r.json() == {"ingested": 1, "alerts": 1, "scope": "DEMO"}

    mgr = login(client, "manager@acme.io")
    inc = next(i for i in client.get("/api/v1/incidents?q=PIPE-TEST-01&page_size=50",
                                     headers=mgr).json()["items"])
    detail = client.get(f"/api/v1/incidents/{inc['id']}", headers=mgr).json()
    facts = detail["evidence_by_kind"]["confirmed_fact"]
    assert any(f["source_ref"].startswith("event:") and f["produced_by"] == "detection:shadow_copy_deletion"
               for f in facts)
    assert detail["incident"]["severity"] == "critical"
    assert detail["sla"]["ack"]["due"]

    # Same pattern again in the same window: de-duplicated into the same alert.
    again = client.post("/api/v1/ingest/events", headers=key, json={"events": [
        {"activity": "Process create", "cmdline": "vssadmin delete shadows", "host": host}]}).json()
    assert again["alerts"] == 0


def test_rule_exceptions_suppress_known_benign(client, admin, manager):
    rules = client.get("/api/v1/detections?page_size=200", headers=manager).json()["items"]
    rule = next(r for r in rules if r["key"] == "encoded_powershell")
    client.patch(f"/api/v1/detections/{rule['id']}", headers=manager,
                 json={"exceptions": [{"host_name": "MGMT-AGENT-01"}]})
    key = _ingest_key(client, {**admin, "X-Tenant-ID": "acme"})
    ev = {"activity": "Process create", "cmdline": "powershell.exe -nop -enc AAAA"}
    suppressed = client.post("/api/v1/ingest/events", headers=key,
                             json={"events": [{**ev, "host": "MGMT-AGENT-01"}]}).json()
    fired = client.post("/api/v1/ingest/events", headers=key,
                        json={"events": [{**ev, "host": "WKS-EXC-02"}]}).json()
    assert suppressed["alerts"] == 0 and fired["alerts"] == 1


def test_threat_intel_rule_matches_tenant_indicators(client, admin):
    key = _ingest_key(client, {**admin, "X-Tenant-ID": "acme"})
    r = client.post("/api/v1/ingest/events", headers=key, json={"events": [
        {"activity": "DNS query", "query": "cdn-metrics-sync.com", "host": "TI-HOST-7"},
        {"activity": "DNS query", "query": "example.org", "host": "TI-HOST-7"}]}).json()
    assert r["alerts"] == 1


def test_ingest_validation(client, admin):
    key = _ingest_key(client, {**admin, "X-Tenant-ID": "acme"})
    assert client.post("/api/v1/ingest/events", headers=key, json={"events": []}).status_code == 422
    assert client.post("/api/v1/ingest/events", headers=key,
                       json={"events": [{}] * 501}).status_code == 413


def test_mock_connector_sync_feeds_demo_pipeline(client, manager):
    c = next(x for x in client.get("/api/v1/connectors", headers=manager).json()["items"]
             if x["kind"] == "splunk")
    client.patch(f"/api/v1/connectors/{c['id']}", headers=manager, json={"enabled": True})
    r = client.post(f"/api/v1/connectors/{c['id']}/sync", headers=manager).json()
    assert r["mock"] is True and r["scope"] == "DEMO" and r["ingested"] >= 1


def test_generator_tick_runs_pipeline_for_demo_customers():
    from astrasoc.seed.engine import _emit_tick

    assert _emit_tick() >= 4  # acme, globex, initech, contoso (+ any test tenants)


def test_ingest_accepts_common_vendor_field_spellings(client, admin):
    """Sysmon/ECS-style names must hit the same detections as canonical ones."""
    key = _ingest_key(client, {**admin, "X-Tenant-ID": "acme"})
    r = client.post("/api/v1/ingest/events", headers=key, json={"events": [{
        "source": "edr", "event_type": "process_creation", "host": "ws-vendor-01", "user": "bob",
        "CommandLine": "powershell.exe -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoA"}]})
    assert r.status_code == 200, r.text
    assert r.json()["alerts"] >= 1
