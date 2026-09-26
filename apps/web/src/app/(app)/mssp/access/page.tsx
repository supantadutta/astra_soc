"use client";

import { useState } from "react";
import { Plus, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/store";
import { DataTable, ErrorState, Modal, PageHeader, Panel, Skeleton } from "@/components/ui";
import { Field, ResultBanner, useAction } from "@/components/mssp";
import { cx, fmtDate, timeAgo, titleCase } from "@/lib/ui";

interface Grant {
  id: string; user_email: string; tenant: string; role_name: string; reason: string;
  created_at: string; expires_at: string | null; revoked_at: string | null; active: boolean;
}

// Roles that exist in every customer tenant. Admin roles cannot be granted.
const GRANTABLE = ["tier1_analyst", "tier2_analyst", "tier3_analyst", "incident_commander", "threat_hunter",
  "detection_engineer", "threat_intel_analyst", "soc_manager", "auditor", "readonly_executive"];

export default function DelegatedAccessPage() {
  const grants = useApi<{ items: Grant[] }>("/mssp/grants");
  const action = useAction();
  const [creating, setCreating] = useState(false);
  const [showInactive, setShowInactive] = useState(false);

  const revoke = async (g: Grant) => {
    if (!confirm(`Revoke ${g.user_email}'s access to ${g.tenant}? It takes effect on their next request.`)) return;
    await action.run(() => api.del(`/mssp/grants/${g.id}`), "Access revoked.");
    grants.reload();
  };
  const rows = (grants.data?.items || []).filter((g) => showInactive || g.active);

  return (
    <div>
      <PageHeader
        title="Delegated Access"
        subtitle="Least-privilege, time-boxed access for individual analysts to specific customers. Every grant and revocation is written to both audit trails."
        actions={<button className="btn-primary" onClick={() => setCreating(true)}><Plus className="w-4 h-4" /> Grant access</button>}
      />
      <Panel className="mb-3">
        <div className="text-xs text-ink-400 space-y-1">
          <p><b className="text-ink-200">How access resolves:</b> platform administrators and SOC managers (<code>mssp:all_customers</code>) reach every customer with the customer&apos;s default provider role; other staff need a grant here.</p>
          <p>Customers can switch provider access off entirely (Organization → Provider access); only platform break-glass can then enter, and it is flagged in red and audited.</p>
        </div>
      </Panel>
      <ResultBanner result={action.result} />
      <Panel
        title="Grants"
        actions={<label className="text-xs text-ink-400 flex items-center gap-1.5"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Show expired/revoked</label>}
      >
        {grants.error ? <ErrorState message={grants.error.message} /> : grants.loading && !grants.data ? <Skeleton rows={4} /> : (
          <DataTable<Grant>
            rows={rows}
            empty="No active grants."
            columns={[
              { key: "user", header: "Analyst", render: (g) => g.user_email },
              { key: "tenant", header: "Customer", render: (g) => g.tenant },
              { key: "role", header: "Role", render: (g) => titleCase(g.role_name) },
              { key: "reason", header: "Justification", render: (g) => <span className="text-xs text-ink-300">{g.reason}</span> },
              { key: "created", header: "Granted", render: (g) => <span className="text-xs text-ink-400">{timeAgo(g.created_at)}</span> },
              { key: "expires", header: "Expires", render: (g) => g.revoked_at ? <span className="text-xs text-crit">revoked</span>
                : g.expires_at ? <span className={cx("text-xs", g.active ? "text-ink-300" : "text-ink-500")}>{fmtDate(g.expires_at)}</span>
                : <span className="text-xs text-amber">no expiry</span> },
              { key: "x", header: "", render: (g) => g.active && (
                <button className="btn-ghost !px-2 !py-1 text-crit" onClick={() => revoke(g)} title="Revoke"><XCircle className="w-3.5 h-3.5" /></button>) },
            ]}
          />
        )}
      </Panel>
      {creating && <GrantModal onClose={() => setCreating(false)} onDone={() => { setCreating(false); grants.reload(); }} />}
    </div>
  );
}

function GrantModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const staff = useApi<{ items: { id: string; email: string; full_name: string; is_active: boolean }[] }>("/mssp/staff");
  const tenants = useApi<{ items: { id: string; name: string; kind: string; status: string }[] }>("/mssp/tenants");
  const action = useAction();
  const [f, setF] = useState({ user_id: "", tenant_id: "", role: "tier2_analyst", reason: "", hours: "72" });
  const customers = (tenants.data?.items || []).filter((t) => t.kind === "customer");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = await action.run(() => api.post("/mssp/grants", {
      user_id: f.user_id, tenant_id: f.tenant_id, role: f.role, reason: f.reason,
      expires_in_hours: f.hours ? Number(f.hours) : undefined,
    }), "Access granted.");
    if (ok) onDone();
  };

  return (
    <Modal open onClose={onClose} title="Grant customer access">
      <form onSubmit={submit} className="space-y-3">
        <ResultBanner result={action.result} />
        <Field label="Analyst">
          <select className="input" required value={f.user_id} onChange={(e) => setF({ ...f, user_id: e.target.value })}>
            <option value="">Select…</option>
            {staff.data?.items.filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.full_name} — {u.email}</option>)}
          </select>
        </Field>
        <Field label="Customer">
          <select className="input" required value={f.tenant_id} onChange={(e) => setF({ ...f, tenant_id: e.target.value })}>
            <option value="">Select…</option>
            {customers.map((t) => <option key={t.id} value={t.id}>{t.name}{t.status !== "active" ? ` (${t.status})` : ""}</option>)}
          </select>
        </Field>
        <Field label="Role in the customer tenant" hint="Admin roles cannot be delegated.">
          <select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            {GRANTABLE.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
          </select>
        </Field>
        <Field label="Justification" hint="Required; shown to the customer in their audit trail.">
          <input className="input" required minLength={5} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="e.g. Covering night shift for INC-2291" />
        </Field>
        <Field label="Expires after (hours)" hint="Leave blank for no expiry (not recommended).">
          <input className="input" type="number" min={1} max={8760} value={f.hours} onChange={(e) => setF({ ...f, hours: e.target.value })} />
        </Field>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={action.busy}>{action.busy ? "Granting…" : "Grant access"}</button>
        </div>
      </form>
    </Modal>
  );
}
