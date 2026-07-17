"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, Loading, PageHeader, Panel } from "@/components/ui";
import { fmtDate, titleCase } from "@/lib/ui";

export default function ApprovalsPage() {
  const { can } = useApp();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<string | null>(null);
  const [status, setStatus] = useState("pending");

  async function load() {
    setLoading(true);
    const r = await api.get<any>(`/approvals?status=${status}`);
    setItems(r.items);
    setLoading(false);
  }
  useEffect(() => { load(); }, [status]);

  async function decide(id: string, decision: "approve" | "reject") {
    try {
      await api.post(`/approvals/${id}/${decision}`, { note: `${decision}d via Approval Center` });
      setToast(`Approval ${decision}d.`);
      load();
    } catch (e: any) { setToast(e.message || "Failed"); }
  }

  return (
    <div>
      <PageHeader title="Approval Center" subtitle="Human authorization for governed response actions" />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}
      <div className="flex gap-2 mb-4">
        {["pending", "approved", "rejected"].map((s) => (
          <button key={s} onClick={() => setStatus(s)} className={`btn-ghost ${status === s ? "!text-cyan !border-cyan/40" : ""}`}>{titleCase(s)}</button>
        ))}
      </div>
      {loading ? <Loading /> : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {items.map((a) => (
            <Panel key={a.id} title={<span className="flex items-center gap-2"><Badge kind="status" value={a.status} /> requires <Badge value="info">{a.required_role}</Badge></span>}>
              <div className="text-sm text-ink-300 mb-1">{a.reason}</div>
              <div className="text-xs text-ink-500 mb-3">Requested {fmtDate(a.created_at)}{a.decided_at ? ` · decided ${fmtDate(a.decided_at)}` : ""}</div>
              {a.status === "pending" && can("approval:decide") && (
                <div className="flex gap-2">
                  <button className="btn-primary !py-1.5" onClick={() => decide(a.id, "approve")}><CheckCircle2 className="w-4 h-4" /> Approve</button>
                  <button className="btn-danger !py-1.5" onClick={() => decide(a.id, "reject")}><XCircle className="w-4 h-4" /> Reject</button>
                </div>
              )}
              {a.decision_note && <div className="text-xs text-ink-400 mt-2">Note: {a.decision_note}</div>}
            </Panel>
          ))}
          {!items.length && <div className="text-ink-500 text-sm py-10 text-center col-span-2">No {status} approvals.</div>}
        </div>
      )}
    </div>
  );
}
