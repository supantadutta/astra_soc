# Quick Start

## 1. Start (Docker, zero credentials)
```bash
docker compose -f docker-compose.demo.yml up --build
```
Web: http://localhost:3000 · API docs: http://localhost:8000/api/docs

## 2. Log in
Use any demo account (see the login page), e.g. `manager@acme.io` / `Demo!Pass123`.

## 3. Walk a scenario end-to-end
1. **SOC Overview** — watch live KPIs and the event stream update in real time.
2. **Incidents** — open `INC-000001` (ransomware precursor).
3. In the workspace, review the **Timeline** and **Evidence & Hypotheses**
   (note how confirmed facts are visually distinct from AI inferences).
4. Click **Run Investigation** — the coordinator runs triage → evidence →
   specialist → independent verification, producing new hypotheses and evidence.
5. Open the **Response** tab, click **Request action** on a recommendation. It
   passes the policy engine and (for critical assets) lands in the Approval Center.
6. As `commander@acme.io`, go to **Approval Center**, approve it.
7. Back on **Response Actions**, **Execute** (simulated in demo), watch it
   **verify**, then **Rollback**.
8. **Audit Logs** → **Verify chain** to confirm the tamper-evident record.
9. **Demo Control Center** — launch more scenarios, pause/speed the generator, reset.

## 4. Configure a real LLM (optional, still demo data)
**AI Model Operations → Add provider**, supply a base URL and a secret
*reference* (e.g. `env://OPENAI_KEY`), set the env var, then **Test** — the
result reflects the real connection.

## Run locally without Docker
```bash
cd apps/api && pip install -r requirements.txt && uvicorn astrasoc.main:app --port 8000
cd apps/web && npm install && npm run dev
```
