# RBAC, Tenancy and Delegation

## Permissions

56 permissions of the form `resource:verb` (for example `incident:read`,
`action:execute`, `evidence:attest`, `mssp:grants`). `resource:*` wildcards
work inside roles; `*` is reserved for the platform super admin. The full
catalogue: `GET /api/v1/rbac/permissions` or
`apps/api/astrasoc/auth/permissions.py`.

Every protected route checks permissions server-side. The UI hides controls a
user lacks, but it is never the authorization boundary. A denial returns 403
with the missing permission.

## Built-in roles

**SOC roles** (present in every tenant): `tenant_admin`, `soc_manager`,
`incident_commander`, `tier3_analyst`, `tier2_analyst`, `tier1_analyst`,
`threat_hunter`, `detection_engineer`, `threat_intel_analyst`, `auditor`,
`readonly_executive`, `integration_service_account`,
`automation_service_account`.

**Platform:** `platform_super_admin` (root provider tenant only).

**Provider roles** (provider and reseller tenants):

| Role | Portfolio | All customers | Onboard | Grants | Content | Handover | Billing |
|------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `provider_admin` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `mssp_soc_manager` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `mssp_analyst` | ✓ | via grants | | | | ✓ | |
| `mssp_account_manager` | ✓ (contractual view) | | ✓ | | | | ✓ |

**Customer roles** (customer tenants): `customer_admin` (manages its own users,
roles, contacts, branding and provider access), `customer_approver` (decides
approvals), `customer_viewer` (read-only incidents, reports and detections).

Customer tenants never contain platform or provider permissions, and a tenant
admin cannot grant them.

## Grant rules

- You cannot create a role with, or assign a role containing, a permission you
  do not hold yourself.
- Wildcards and platform permissions cannot be granted by tenant admins.
- API keys: explicit scopes only, never more than the creator holds, bound to
  the issuing tenant, 1–365 day expiry.
- **Temporary elevation:** role assignments may carry an expiry
  (`UserRole.expires_at`); expired assignments are ignored at request time.

## Approval authority

Approval steps name a required role. The approver must hold `approval:decide`
**and** a role with authority for that step (for example an incident
commander's step may be decided by an incident commander or a SOC manager).
The mapping is `APPROVAL_AUTHORITY` in `auth/permissions.py`.

## Four-eyes controls

- Detection rules must be approved by someone other than their author.
- Shift handovers must be acknowledged by someone other than their author.

## Tenant isolation and delegation

Every operational row carries `tenant_id`, and every query filters by the
acting tenant and its data scope. Provider staff enter customers through
delegation (platform, provider-wide, per-analyst grant, or audited
break-glass). The rules are in [MSSP](MSSP.md#how-provider-staff-reach-customer-data).

## Management endpoints

- `/api/v1/rbac/*`: roles, permission matrix, users and assignments (acting
  tenant).
- `/api/v1/tenants`, `/api/v1/tenants/current`: tenants the caller can act in;
  own-organization self-service.
- `/api/v1/mssp/*`: portfolio, customer lifecycle, grants (provider staff).
- `/api/v1/auth/*`: sessions, password, API keys.
