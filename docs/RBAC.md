# RBAC & Tenant Isolation

## Roles (14, all server-enforced)
platform_super_admin, tenant_admin, soc_manager, incident_commander,
tier3_analyst, tier2_analyst, tier1_analyst, threat_hunter, detection_engineer,
threat_intel_analyst, auditor, readonly_executive, integration_service_account,
automation_service_account.

Permissions are `resource:verb` strings (e.g. `incident:read`,
`action:execute`). `*` = all (super admin only); `resource:*` wildcards work.
See `apps/api/astrasoc/auth/permissions.py` for the full catalogue.

## Enforcement
Every protected route depends on `require_permission("…")`, which re-checks
server-side. The frontend only hides controls a user lacks — it is never the
authorization boundary. A denied call returns a standard 403 with the required
permission.

## Effective permissions
Union of a user's active roles. **Temporary elevation** is supported via
`UserRole.expires_at`; expired assignments are ignored at request time.

## Approval delegation
The Approval Center enforces that the approver holds the role the policy required
(`ApprovalRequest.required_role`).

## Tenant isolation
Every operational row carries `tenant_id`. Queries filter by the caller's tenant;
knowledge retrieval additionally filters by scope and classification. Cross-tenant
cases, events, embeddings and model context are prevented.

## Management
`/api/v1/rbac/*` (roles, permission matrix, users, assignments) and
`/api/v1/tenants/*`. Built-in roles cannot be edited; create custom roles freely.
Sessions, login history and API tokens are managed under `/auth/*`.
