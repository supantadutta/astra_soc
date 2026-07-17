"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, DataTable, Loading, Modal, PageHeader } from "@/components/ui";
import { fmtDate, titleCase } from "@/lib/ui";

export default function ResponsePage() {
  const { can } = useApp();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<any>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [status, setStatus] = useState("");

  async function load() {
    setLoading(true);
    const r = await api.get<any>(`/response/actions${status ? `?status=${status}` : ""}`);
    setItems(r.items);
    setLoading(false);
  }
  useEffect(() => { load(); }, [status]);

  async function openDetail(id: string) {
    setDetail(await api.get<any>(`/response/actions/${id}`));
  }

  async function op(id: string, action: string) {
    try {
      await api.post(`/response/actions/${id}/${action}`);
      setToast(`${titleCase(action)} complete.`);
      await openDetail(id);
      load();
    } catch (e: any) { setToast(e.message); }
  }

  return (
    <div>
      <PageHeader title="Response Actions" subtitle="Every action passes schema → evidence → policy → approval → dry-run → execute → verify" />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}
      <div className="flex gap-2 mb-4">
        {["", "pending_approval", "approved", "verified", "rolled_back", "blocked_by_policy"].map((s) => (
          <button key={s} onClick={() => setStatus(s)} className={`btn-ghost !text-xs ${status === s ? "!text-cyan !border-cyan/40" : ""}`}>{s ? titleCase(s) : "All"}</button>
        ))}
      </div>
      <div className="panel p-4">
        {loading ? <Loading /> : (
          <DataTable
            rows={items}
            onRow={(r: any) => openDetail(r.id)}
            columns={[
              { key: "action_type", header: "Action", render: (r: any) => <span className="text-ink-100">{titleCase(r.action_type)}</span> },
              { key: "target", header: "Target", render: (r: any) => <span className="text-xs text-ink-400 font-mono">{r.target?.value}</span> },
              { key: "status", header: "Status", render: (r: any) => <Badge kind="status" value={r.status} /> },
              { key: "confidence", header: "Conf", render: (r: any) => <span className="tabular-nums">{Math.round((r.confidence || 0) * 100)}%</span> },
              { key: "reversible", header: "Reversible", render: (r: any) => (r.reversible ? "yes" : "no") },
              { key: "simulated", header: "Mode", render: (r: any) => <Badge value={r.simulated ? "info" : "critical"}>{r.simulated ? "SIM" : "LIVE"}</Badge> },
              { key: "created_at", header: "Created", render: (r: any) => <span className="text-ink-400 text-xs">{fmtDate(r.created_at)}</span> },
            ]}
          />
        )}
      </div>

      <Modal open={!!detail} onClose={() => setDetail(null)} title="Response Action" wide>
        {detail && (
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-2">
              <Badge kind="status" value={detail.action.status} />
              <span className="text-ink-100 font-medium">{titleCase(detail.action.action_type)}</span>
              <span className="text-ink-500 font-mono text-xs">{detail.action.target?.value}</span>
            </div>
            <Field label="Expected outcome">{detail.action.expected_outcome}</Field>
            <Field label="Blast radius">{JSON.stringify(detail.action.blast_radius)}</Field>
            <Field label="Supporting evidence">{detail.action.supporting_evidence_ids?.length || 0} item(s)</Field>
            {detail.policy_decision && (
              <div className="rounded-lg border border-white/5 p-3">
                <div className="label mb-1">Policy decision</div>
                <Badge value={detail.policy_decision.effect === "allow" ? "approved" : detail.policy_decision.effect === "deny" ? "rejected" : "pending"}>{detail.policy_decision.effect}</Badge>
                <ul className="text-xs text-ink-400 mt-1 list-disc pl-4">
                  {detail.policy_decision.reasons?.map((r: string, i: number) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            )}
            {detail.action.dry_run_result?.note && <Field label="Dry-run">{detail.action.dry_run_result.note}</Field>}
            {detail.action.execution_result?.summary && <Field label="Execution">{detail.action.execution_result.summary}</Field>}
            {detail.action.verification_result?.verified != null && (
              <Field label="Verification"><span className={detail.action.verification_result.verified ? "text-teal" : "text-crit"}>{detail.action.verification_result.verified ? "verified ✓" : "verification failed ✗"}</span></Field>
            )}

            <div className="flex flex-wrap gap-2 pt-2 border-t border-white/5">
              {can("action:request") && <button className="btn-ghost" onClick={() => op(detail.action.id, "dry-run")}>Dry-run</button>}
              {can("action:execute") && detail.action.status === "approved" && <button className="btn-primary" onClick={() => op(detail.action.id, "execute")}>Execute</button>}
              {can("action:execute") && detail.action.status === "succeeded" && <button className="btn-ghost" onClick={() => op(detail.action.id, "verify")}>Verify</button>}
              {can("action:execute") && ["verified", "succeeded"].includes(detail.action.status) && detail.action.reversible && <button className="btn-violet" onClick={() => op(detail.action.id, "rollback")}>Rollback</button>}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><span className="label">{label}: </span><span className="text-ink-300">{children}</span></div>;
}
