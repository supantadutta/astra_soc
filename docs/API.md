# API

Base path `/api/v1`. Interactive docs at `/api/docs` (Swagger) and
`/api/redoc`; OpenAPI JSON at `/api/openapi.json`. 156 operations.

## Conventions

- **Authentication:** `Authorization: Bearer <access token>` (from
  `POST /auth/login`, refreshed with `POST /auth/refresh`) or
  `X-API-Key: <key>`.
- **Tenant context:** add `X-Tenant-ID: <tenant id or slug>` to act inside
  another tenant you are allowed to reach (MSSP delegation). Omit it to act in
  your home tenant. `403 tenant_access_denied` if not allowed.
- **Pagination:** `?page=1&page_size=25` → `{items, total, page, page_size, pages}`.
- **Errors:** `{error, message, request_id, detail?}` with the proper status;
  validation errors are 422, plan limits `403 feature_not_in_plan`, egress
  violations `422 egress_blocked`.
- **Tracing:** every response has `x-request-id` and `x-response-time-ms`.
- **Rate limits:** per credential (authenticated) or per client IP; `429` with
  `retry-after`.
- **Idempotency:** playbook runs accept `idempotency_key`.

## Groups

| Group | Prefix |
|-------|--------|
| Sign-in, sessions, password, API keys, `/me`, login options | `/auth` |
| Operating mode (per tenant), readiness, health | `/mode`, `/health/live`, `/health/ready`, `/system` |
| Dashboard, platform health | `/dashboard`, `/platform` |
| Alerts, incidents, entities | `/alerts`, `/incidents`, `/entities` |
| Event ingestion (log forwarders) | `POST /ingest/events` (≤ 500 events per call, `event:ingest`) |
| Live event stream | `POST /stream/ticket` → `GET /stream?ticket=` (SSE) |
| Agents and runs | `/agents` |
| Models, routing | `/models` |
| Connectors | `/connectors` |
| Detections, query | `/detections`, `/query` |
| Threat intelligence | `/threat-intel` |
| Playbooks and runs | `/playbooks` |
| Response actions and approvals | `/response`, `/approvals` |
| Knowledge | `/knowledge` |
| Reports | `/reports` |
| RBAC | `/rbac` |
| Tenants you can act in; own organization | `/tenants`, `/tenants/current` |
| **MSSP portfolio and lifecycle** | `/mssp` |
| Notifications | `/notifications` |
| Audit log and chain verification | `/audit`, `/audit/verify` |
| Controlled learning and offline evaluations | `/learning` |
| Demo control (platform admin) | `/demo` |

## MSSP endpoints

| Method and path | Permission (home tenant) | Purpose |
|-----------------|--------------------------|---------|
| `GET /mssp/overview` | `mssp:portfolio` | Per-customer health, SLA and workload |
| `GET /mssp/queue` | `mssp:portfolio` | Unified open-incident queue (`severity`, `sla`, `tenant`, `status` filters) |
| `GET /mssp/sla?period=YYYY-MM` | `mssp:portfolio` | SLA compliance per customer |
| `GET /mssp/usage?period=&format=json\|csv` | `mssp:billing` | Metered usage |
| `GET /mssp/catalog` | `mssp:portfolio` | Tiers, SLA defaults, features |
| `GET/POST /mssp/tenants`, `GET/PATCH /mssp/tenants/{id}` | `mssp:portfolio` / `mssp:onboard` | List, onboard, read, update contract |
| `POST /mssp/tenants/{id}/suspend`, `/activate` | `mssp:onboard` | Lifecycle |
| `GET /mssp/tenants/{id}/export` | `mssp:onboard` | Data export (no credentials or hashes) |
| `DELETE /mssp/tenants/{id}` body `{"confirm": "<slug>"}` | `mssp:onboard` | Offboard (tenant must be suspended) |
| `GET /mssp/staff`, `GET/POST /mssp/grants`, `DELETE /mssp/grants/{id}` | `mssp:grants` | Delegated access |
| `GET /mssp/content/detections`, `POST …/{rule_id}/deploy` | `mssp:content` | Content distribution |
| `GET/POST /mssp/handovers`, `POST …/{id}/acknowledge` | `mssp:handover` | Shift handover |
| `POST /mssp/reports/service` | `mssp:portfolio` | Monthly service reports into customer tenants |
| `GET /mssp/notifications` | `mssp:portfolio` | Provider notifications, including customer escalations |

## Example: forward events

```bash
curl -X POST https://soc.example.com/api/v1/ingest/events \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"events":[{"source":"edr","event_type":"process_creation","host":"FIN-WKS-014",
       "user":"acme\\jdoe","CommandLine":"powershell.exe -enc SQBFAFgA..."}]}'
# → {"ingested":1,"alerts":1,"scope":"LIVE"}
```

Common Sysmon, Windows Security and ECS spellings (`CommandLine`,
`process_creation`, `4688`, `dns.question.name`, …) are normalised
automatically.

## Example: act inside a customer

```bash
curl https://soc.example.com/api/v1/incidents \
  -H "Authorization: Bearer $TOKEN" -H "X-Tenant-ID: acme"
```
