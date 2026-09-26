# Quick Start

## 1. Start the demo (Docker, zero credentials)

```bash
docker compose -f docker-compose.demo.yml up --build
```

Web: <http://localhost:3000>. API docs: <http://127.0.0.1:8000/api/docs>.

Or without Docker:

```bash
cd apps/api && pip install -r requirements.txt && uvicorn astrasoc.main:app --port 8000
cd apps/web && npm install && npm run dev
```

The demo seeds an MSSP (**ASTRASOC Managed Security**), a reseller
(Northwind) and four customers on different tiers and regions, with 29
realistic incidents and continuously generated telemetry. All demo accounts
use the password `Demo!Pass123` and are listed on the sign-in page.

## 2. The MSSP view: `soc@astrasoc.io`

1. **Portfolio**: every customer, worst first, with SLA breaches and at-risk
   counts.
2. **Unified Queue**: all open incidents across customers, SLA-first. Open
   one: you switch into that customer and a purple banner shows that you are
   acting as the customer's SOC manager, with every action recorded in *their*
   audit trail.
3. **Customers → Onboard customer**: create a tenant with a tier, region,
   contract dates and a first admin. It is ready immediately.
4. **Delegated Access**: grant `analyst@astrasoc.io` time-boxed Tier-2 access
   to one customer. Sign in as the analyst: only granted customers appear in
   the switcher.
5. **Usage & Billing → Generate service reports**, then open a customer's
   **Reports**.

## 3. The investigation workflow: `manager@acme.io`

1. **Incidents** → open `INC-000001` (ransomware precursor). Note the SLA clock.
2. **Acknowledge** (stops the acknowledgement clock), add a note, review
   **Evidence & Hypotheses**. Confirmed facts come from telemetry; AI output is
   labelled as inference.
3. **Run Investigation**: bounded agents triage, gather evidence and
   independently verify; invented evidence citations are dropped.
4. **Response** tab → **Request action** on a recommendation; it passes the
   policy engine and, if needed, lands in the **Approval Center** (approve as
   `commander@acme.io`).
5. **Audit Logs → Verify chain**.

## 4. The customer's view: `ciso@acme.io`

**Organization → Provider access**: switch the MSSP's access off. Provider
staff lose access on their next request (only audited break-glass remains).
Switch it back on afterwards.

## 5. Connect a real LLM (optional)

AI Model Operations → **Add provider**. Give a base URL and a secret
*reference* in the tenant's namespace, e.g.
`vault://tenants/acme/openai#api_key`. Without a Vault server, that reference
resolves from the environment variable
`ASTRASOC_SECRET_TENANTS_ACME_OPENAI_API_KEY`. Click **Test**: the result
reflects the real connection. Then set the tenant's LLM strategy (Settings) to
`hosted` or `hybrid`. The Enterprise tier includes external LLMs; others need a
contract override.
