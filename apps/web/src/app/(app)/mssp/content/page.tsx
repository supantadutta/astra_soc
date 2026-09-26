"use client";

import { useState } from "react";
import { Send } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/store";
import { Badge, DataTable, ErrorState, Modal, PageHeader, Panel, Skeleton } from "@/components/ui";
import { ResultBanner, useAction } from "@/components/mssp";
import { cx } from "@/lib/ui";

interface Rule {
  id: string; key: string; name: string; severity: string; status: string; version: number;
  attack_techniques: string[]; ai_generated: boolean; approved_by: string | null; enabled: boolean;
}
interface DeployResult { tenant_id: string; tenant?: string; status: string; reason?: string }

export default function ContentDistributionPage() {
  const lib = useApi<{ items: Rule[] }>("/mssp/content/detections");
  const [deploying, setDeploying] = useState<Rule | null>(null);

  return (
    <div>
      <PageHeader
        title="Content Distribution"
        subtitle="Publish your provider detection library to customers. Customers receive a managed, versioned copy; their local exceptions are preserved on redeploy and customer-owned rules are never overwritten."
      />
      <Panel>
        {lib.error ? <ErrorState message={lib.error.message} /> : lib.loading && !lib.data ? <Skeleton rows={6} /> : (
          <DataTable<Rule>
            rows={lib.data?.items || []}
            empty="Your provider tenant has no detection rules yet. Author them under Detection Engineering while in your home tenant."
            columns={[
              { key: "name", header: "Rule", render: (r) => <div><div className="text-ink-100">{r.name}</div><div className="text-[10px] font-mono text-ink-500">{r.key} · v{r.version}</div></div> },
              { key: "severity", header: "Severity", render: (r) => <Badge kind="severity" value={r.severity} /> },
              { key: "attack", header: "ATT&CK", render: (r) => <span className="text-xs text-ink-400">{r.attack_techniques?.join(", ") || "—"}</span> },
              { key: "status", header: "Status", render: (r) => <Badge kind="status" value={r.status === "deployed" ? "completed" : r.status}>{r.status}</Badge> },
              { key: "ai", header: "Origin", render: (r) => r.ai_generated ? <span className={cx("text-xs", r.approved_by ? "text-violet" : "text-amber")}>AI{r.approved_by ? " · approved" : " · unapproved"}</span> : <span className="text-xs text-ink-400">Human</span> },
              { key: "deploy", header: "", render: (r) => (
                <button className="btn-primary !py-1 !text-xs" disabled={!["approved", "deployed"].includes(r.status)}
                  title={["approved", "deployed"].includes(r.status) ? "Distribute to customers" : "Only approved or deployed rules can be distributed"}
                  onClick={(e) => { e.stopPropagation(); setDeploying(r); }}>
                  <Send className="w-3.5 h-3.5" /> Distribute
                </button>) },
            ]}
          />
        )}
      </Panel>
      {deploying && <DeployModal rule={deploying} onClose={() => setDeploying(null)} />}
    </div>
  );
}

function DeployModal({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const portfolio = useApi<{ customers: { id: string; name: string; service_tier: string; provider_access: boolean }[] }>("/mssp/overview");
  const action = useAction();
  const [all, setAll] = useState(true);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<DeployResult[] | null>(null);
  const names = Object.fromEntries((portfolio.data?.customers || []).map((c) => [c.id, c.name]));

  const go = async () => {
    await action.run(async () => {
      const res = await api.post<{ results: DeployResult[] }>(`/mssp/content/detections/${rule.id}/deploy`,
        all ? { all: true } : { tenant_ids: Array.from(picked) });
      setResults(res.results);
    }, "Distribution finished — see per-customer results below.");
  };

  return (
    <Modal open onClose={onClose} title={`Distribute “${rule.name}” v${rule.version}`} wide>
      <ResultBanner result={action.result} />
      {!results ? (
        <>
          <label className="flex items-center gap-2 text-sm mb-2"><input type="radio" checked={all} onChange={() => setAll(true)} /> All customers I operate</label>
          <label className="flex items-center gap-2 text-sm mb-2"><input type="radio" checked={!all} onChange={() => setAll(false)} /> Selected customers</label>
          {!all && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-1 max-h-64 overflow-y-auto border border-white/5 rounded-lg p-2 mb-2">
              {portfolio.data?.customers.map((c) => (
                <label key={c.id} className="flex items-center gap-2 text-xs">
                  <input type="checkbox" checked={picked.has(c.id)} disabled={!c.provider_access}
                    onChange={(e) => { const n = new Set(picked); if (e.target.checked) n.add(c.id); else n.delete(c.id); setPicked(n); }} />
                  {c.name}{!c.provider_access && <span className="text-crit"> (access off)</span>}
                </label>
              ))}
            </div>
          )}
          <div className="flex justify-end gap-2 mt-3">
            <button className="btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn-primary" onClick={go} disabled={action.busy || (!all && !picked.size)}>{action.busy ? "Distributing…" : "Distribute"}</button>
          </div>
        </>
      ) : (
        <>
          <table className="w-full text-sm">
            <tbody>
              {results.map((r) => (
                <tr key={r.tenant_id} className="border-b border-white/5">
                  <td className="py-1.5">{r.tenant || names[r.tenant_id] || r.tenant_id}</td>
                  <td className={cx("py-1.5 text-xs", r.status === "skipped" ? "text-amber" : "text-teal")}>{r.status}</td>
                  <td className="py-1.5 text-xs text-ink-400">{r.reason || ""}</td>
                </tr>
              ))}
              {!results.length && <tr><td className="py-4 text-center text-ink-500">No customers were targeted.</td></tr>}
            </tbody>
          </table>
          <div className="flex justify-end mt-3"><button className="btn-ghost" onClick={onClose}>Close</button></div>
        </>
      )}
    </Modal>
  );
}
