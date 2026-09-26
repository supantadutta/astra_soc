# Running ASTRASOC as an MSSP

ASTRASOC is built for managed security service providers: one deployment
serves the provider's own SOC and many customer organisations, each fully
isolated, with contractual SLAs, delegated analyst access and per-customer
metering.

## Tenant hierarchy

```
ASTRASOC Managed Security        (provider — the root tenant, your MSSP)
├── Acme Corporation             (customer, enterprise tier, US)
├── Globex Manufacturing         (customer, professional tier, EU)
├── Initech Financial            (customer, essentials tier, US)
└── Northwind Security           (reseller / partner)
    └── Contoso Retail           (customer managed through the reseller)
```

| Kind | Purpose |
|------|---------|
| `provider` | The MSSP operating the platform. Its staff hold `mssp:*` permissions. |
| `reseller` | A partner that operates its own customers underneath the provider. Resellers see only their own subtree. |
| `customer` | An organisation whose security is managed. Customers never see the provider, peers, or other customers. |

Every tenant has a **status** (`onboarding`, `active`, `suspended`,
`offboarding`), a **service tier**, a **data-residency region**, contract dates,
escalation contacts, report branding and a **delegation policy**. Suspended
tenants cannot sign in; their users' sessions stop working on the next request.

## How provider staff reach customer data

Provider users sign in to their home (provider) tenant and switch into a
customer with the tenant switcher (the API receives `X-Tenant-ID`). Access is
re-evaluated **on every request**, so revocations take effect immediately.

| Path | Who | Role inside the customer |
|------|-----|--------------------------|
| `provider` | Staff with `mssp:all_customers` (SOC managers, provider admins) | The customer's `default_provider_role` (default `soc_manager`) |
| `grant` | Any staff member with an active **access grant** | The role named in the grant (never an admin role) |
| `platform` | Platform administrators | The customer's default provider role |
| `break_glass` | Platform administrators when the customer has switched provider access **off** | Same, but flagged in red in the UI and in every audit entry |

Rules that always hold:

- Acting permissions are the **customer tenant's own role permissions** minus
  any platform (`platform:*`) or provider (`mssp:*`) permissions. Delegation
  can never escalate beyond what the customer's role allows.
- Every delegated action is recorded in the **customer's** audit trail with the
  real analyst and the access path, for example
  `Lee Park <analyst@astrasoc.io> [via astrasoc/grant]`.
- Customers control access themselves (Organization → Provider access): switch
  provider access off, choose the default provider role, and restrict which
  roles may be granted. Provider staff cannot change this policy.
- API keys are bound to the tenant that issued them and re-check delegation on
  each use.
- **MFA:** a customer that requires two-step verification requires it of
  everyone acting inside it. Provider staff can only enter with an
  MFA-verified session (their API keys cannot enter at all), and the tenant
  switcher marks such customers with a lock. The provider can impose the
  requirement on a customer from the contract editor, but cannot lift one the
  customer set.

## Service tiers and entitlements

| Feature | Essentials | Professional | Enterprise |
|---------|:---:|:---:|:---:|
| 24×7 monitoring and triage | ✓ | ✓ | ✓ |
| Service reports | ✓ | ✓ | ✓ |
| Threat-intel enrichment | ✓ | ✓ | ✓ |
| AI-assisted investigation (agents) | | ✓ | ✓ |
| Threat hunting (query workbench) | | ✓ | ✓ |
| Governed response actions / playbooks | | ✓ | ✓ |
| Customer-specific detection engineering | | | ✓ |
| External / private LLM providers | | | ✓ |

Entitlements are enforced by the API (`403 feature_not_in_plan`), not just
hidden in the UI. A contract can force individual features on or off per
customer (Customers → Edit contract → Feature entitlements).

Default SLA targets (acknowledge / resolve), overridable per contract and per
severity:

| Severity | Essentials | Professional | Enterprise |
|----------|-----------|--------------|------------|
| Critical | 60 min / 24 h | 30 min / 8 h | 15 min / 4 h |
| High | 240 min / 48 h | 120 min / 24 h | 60 min / 12 h |
| Medium | 1440 min / 120 h | 480 min / 72 h | 240 min / 48 h |
| Low | 2880 min / 240 h | 1440 min / 168 h | 720 min / 120 h |
| Info | 10080 min / 720 h | 4320 min / 336 h | 2880 min / 240 h |

The live values are served by `GET /api/v1/mssp/catalog`.

## SLA engine

- Each incident gets `sla_ack_due` / `sla_resolve_due` from the customer's
  effective SLA when it is created (or when its severity changes).
- Acknowledging stops the acknowledgement clock; resolving stops the resolution
  clock.
- A background sweeper runs every 60 seconds. When a clock is breached it marks
  the breach, raises the incident's escalation level, and notifies the customer
  and the provider chain (including resellers). Each notification records its
  real delivery outcome: `sent`, `failed`, `not_configured` or `simulated`.
- **SLA Compliance** reports, per customer and month, how many decided clocks
  were met, plus MTTA / MTTR and currently open breaches.

## Managed Service console

| Page | What it does |
|------|--------------|
| **Portfolio** | Every customer you are responsible for, worst first: open incidents by severity, SLA breaches / at-risk, approvals, connector health, contract expiry, and whether the customer allows provider access. |
| **Unified Queue** | Open incidents across all customers, ordered SLA-breached → at-risk → severity → time remaining. Opening a row switches into that customer. |
| **SLA Compliance** | Contractual compliance per customer and period. |
| **Customers** | Onboard (with first customer admin), edit contract (tier, status, region, dates, feature overrides, SLA overrides), suspend / activate, export data (no credentials or password hashes), offboard (type the slug to confirm; audit records are retained). |
| **Delegated Access** | Time-boxed, justified grants of a customer role to an individual analyst. Grants and revocations are written to both audit trails. |
| **Content Distribution** | Publish approved provider detections to all or selected customers as managed, versioned copies. Customer tuning (exceptions) survives redeploys; customer-owned rules with the same key are never overwritten. |
| **Shift Handover** | Structured handover with open items linked to incidents; the incoming shift acknowledges (authors cannot acknowledge their own). |
| **Usage & Billing** | Metered usage per customer and month (events ingested, alerts, incidents, agent runs, LLM tokens, reports), CSV export, and one-click monthly service reports stored in each customer's tenant. |

## Customer self-service

Customer administrators manage their own users and roles (never platform or
provider permissions), escalation contacts, report branding, API keys for log
forwarders, and the provider-access policy. They see their contract, tier and
SLA read-only.

## Data isolation

- Every operational query filters by the acting tenant **and** the tenant's
  current data scope (DEMO or LIVE; each tenant has its own operating mode).
- Secret references are confined to the tenant namespace
  (`vault://tenants/<slug>/…`).
- Model routes can only use the tenant's own model deployments; AI calls obey
  the tenant's region, data classification and private-model policy.
- The live event stream delivers only the acting tenant's events (plus the
  provider's own events for provider staff).

Automated tests covering these guarantees live in
`apps/api/tests/test_mssp.py` and `apps/api/tests/test_tenant_isolation.py`.

## Onboarding a customer (checklist)

1. **Customers → Onboard customer**: name, slug, tier, region, contract dates,
   security contact, and the first customer admin.
2. The new tenant is provisioned with roles, the managed detection library,
   connector definitions and the built-in AI reasoner.
3. Create an ingest API key in the customer tenant (My Account → API keys,
   preset "Log forwarder") and point the customer's forwarder at
   `POST /api/v1/ingest/events` with the `X-API-Key` header.
4. Configure connectors with `vault://tenants/<slug>/…` secret references and
   run **Test connection** — status is only ever shown healthy after a real
   test succeeds.
5. Set the status to **Active** and switch the tenant to LIVE when readiness
   checks pass (Settings).
