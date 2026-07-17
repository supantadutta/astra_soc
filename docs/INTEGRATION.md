# Integration Guide

## Connector framework
Each connector (`services/connectors`) provides: setup form, secret-reference
config, **test connection**, health status, last sync/error, enable/disable, data
mappings, collection interval, rate-limit, **read/write permission separation**,
and a mock server for testing.

## Catalog (28)
- **SIEM/analytics:** CrowdStrike LogScale, Splunk, Microsoft Sentinel,
  Elastic/OpenSearch, Generic REST SIEM, Generic syslog.
- **EDR/XDR/NDR:** CrowdStrike Falcon, Microsoft Defender, Vectra, Stellar Cyber,
  Generic EDR/NDR.
- **Identity:** Entra ID, Active Directory, Keycloak, Generic LDAP (read).
- **Threat intel:** MISP, VirusTotal, TAXII, Generic STIX/TAXII.
- **ITSM/comms:** ServiceNow, Jira, Slack, Microsoft Teams, Email webhook.
- **Cloud:** AWS, Azure, GCP, Kubernetes audit logs.

## Configuring a connector
1. **Integrations** → pick a connector → **Configure**.
2. Uncheck **Use built-in mock server**, set the base URL and a secret reference
   (e.g. `vault://splunk#token`) and set the env var.
3. **Test connection** — the result reflects the real endpoint (or `not_configured`).
4. Enable read and/or write (write = response actions).

## Health is truthful
In mock mode a connector reports `healthy (mock)`. In real mode it performs an
HTTP probe; auth failure → `unhealthy`, missing base URL/secret → `not_configured`.
Never a fake success.

## Mock server for contract tests
```bash
uvicorn astrasoc.services.connectors.mock_server:mock_app --port 9900
```
Implements minimal Splunk/CrowdStrike/generic endpoints with a valid-token check.
