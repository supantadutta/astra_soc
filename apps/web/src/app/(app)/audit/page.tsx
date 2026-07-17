"use client";

import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api, qs } from "@/lib/api";
import { Badge, DataTable, Loading, PageHeader, Panel } from "@/components/ui";
import { fmtDate } from "@/lib/ui";

export default function AuditPage() {
  const [data, setData] = useState<any>(null);
  const [chain, setChain] = useState<any>(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.get<any>(`/audit${qs({ q, page, page_size: 50 })}`).then(setData);
  }, [q, page]);

  async function verify() {
    setChain(await api.get<any>("/audit/verify"));
  }

  return (
    <div>
      <PageHeader title="Audit Logs" subtitle="Append-only, hash-chained, tamper-evident"
        actions={<button className="btn-primary" onClick={verify}><ShieldCheck className="w-4 h-4" /> Verify chain</button>} />
      {chain && (
        <div className={`mb-3 text-sm rounded-lg px-3 py-2 border ${chain.verified ? "text-teal bg-teal/10 border-teal/30" : "text-crit bg-crit/10 border-crit/30"}`}>
          {chain.verified ? `✓ Chain verified across ${chain.checked} entries — no tampering detected.` : `✗ Chain BROKEN at entry ${chain.broken_at}.`}
        </div>
      )}
      <input className="input max-w-sm mb-4" placeholder="Search audit events…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      <Panel>
        {!data ? <Loading /> : (
          <>
            <DataTable
              rows={data.items}
              columns={[
                { key: "created_at", header: "Time", render: (r: any) => <span className="text-xs text-ink-400 whitespace-nowrap">{fmtDate(r.created_at)}</span> },
                { key: "action", header: "Action", render: (r: any) => <span className="font-mono text-xs text-cyan">{r.action}</span> },
                { key: "actor_label", header: "Actor", render: (r: any) => <span className="text-xs">{r.actor_label || r.actor_type}</span> },
                { key: "resource_type", header: "Resource", render: (r: any) => <span className="text-xs text-ink-400">{r.resource_type}</span> },
                { key: "outcome", header: "Outcome", render: (r: any) => <Badge value={r.outcome === "success" ? "healthy" : "unhealthy"}>{r.outcome}</Badge> },
                { key: "data_scope", header: "Scope", render: (r: any) => <Badge value="info">{r.data_scope}</Badge> },
                { key: "entry_hash", header: "Hash", render: (r: any) => <span className="font-mono text-[10px] text-ink-500">{r.entry_hash?.slice(0, 12)}…</span> },
              ]}
            />
            {data.pages > 1 && (
              <div className="flex items-center justify-between mt-3 text-sm text-ink-400">
                <span>Page {data.page} / {data.pages} · {data.total} entries</span>
                <div className="flex gap-2">
                  <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Prev</button>
                  <button className="btn-ghost" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>Next</button>
                </div>
              </div>
            )}
          </>
        )}
      </Panel>
    </div>
  );
}
