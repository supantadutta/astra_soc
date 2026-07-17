# API

Base path `/api/v1`. Interactive docs at `/api/docs` (Swagger) and `/api/redoc`.
OpenAPI JSON at `/api/openapi.json`. **105 routes.**

## Conventions
- **Auth:** `Authorization: Bearer <jwt>` or `X-API-Key: <key>`.
- **Pagination:** `?page=1&page_size=25`; responses are `{items,total,page,page_size,pages}`.
- **Filter/sort/search:** per-resource query params + `?q=` search, `?sort=&order=asc|desc`.
- **Errors:** `{error, message, request_id, detail?}` with the right HTTP status.
- **Request IDs:** every response carries `x-request-id` (and `x-response-time-ms`).
- **Rate limiting:** per-IP; `429` with `retry-after` when exceeded.
- **Idempotency:** response actions carry an idempotency key; workflows accept one.

## Key groups
| Group | Prefix |
|-------|--------|
| Auth / sessions / API keys | `/auth` |
| Mode & system health | `/mode`, `/health/*`, `/system/*` |
| Dashboard & platform health | `/dashboard/*`, `/platform/*` |
| Alerts / Incidents / Entities | `/alerts`, `/incidents`, `/entities` |
| Agents & runs | `/agents` |
| Models / routing | `/models` |
| Connectors | `/connectors` |
| Detections & Query | `/detections`, `/query` |
| Threat intel | `/threat-intel` |
| Playbooks & workflow runs | `/playbooks` |
| Response actions & approvals | `/response`, `/approvals` |
| Knowledge | `/knowledge` |
| Reports | `/reports` |
| RBAC / tenants | `/rbac`, `/tenants` |
| Audit | `/audit` |
| Controlled learning | `/learning` |
| Demo control | `/demo` |
| Live event stream (SSE) | `/stream` |

## Example: governed response
```
POST /response/actions            # create → runs safety pipeline
POST /approvals/{id}/approve      # incident commander approves
POST /response/actions/{id}/execute
POST /response/actions/{id}/verify
POST /response/actions/{id}/rollback
```
