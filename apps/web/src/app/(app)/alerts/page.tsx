"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, qs } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, ConfidenceBar, DataTable, Loading, PageHeader } from "@/components/ui";
import type { Alert, Page } from "@/lib/types";
import { timeAgo, titleCase } from "@/lib/ui";

export default function AlertsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { can } = useApp();
  const [data, setData] = useState<Page<Alert> | null>(null);
  const [severity, setSeverity] = useState(params.get("severity") || "");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [toast, setToast] = useState<string | null>(null);

  async function load() {
    setData(await api.get<Page<Alert>>(`/alerts${qs({ severity, status, q, page_size: 30 })}`));
  }
  useEffect(() => { load(); }, [severity, status, q]);

  async function act(id: string, action: "acknowledge" | "promote") {
    try {
      const res = await api.post<any>(`/alerts/${id}/${action}`);
      if (action === "promote") { setToast("Incident created."); router.push(`/incidents/${res.id}`); }
      else { setToast("Alert acknowledged."); load(); }
    } catch (e: any) { setToast(e.message); }
  }

  return (
    <div>
      <PageHeader title="Alerts" subtitle={`${data?.total ?? "—"} alerts · deterministic detections`} />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}
      <div className="flex flex-wrap gap-2 mb-4">
        <input className="input max-w-xs" placeholder="Search alerts…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input max-w-[160px]" value={severity} onChange={(e) => setSeverity(e.target.value)}>
          {["", "critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{s ? titleCase(s) : "All severities"}</option>)}
        </select>
        <select className="input max-w-[160px]" value={status} onChange={(e) => setStatus(e.target.value)}>
          {["", "new", "acknowledged", "investigating", "closed"].map((s) => <option key={s} value={s}>{s ? titleCase(s) : "All statuses"}</option>)}
        </select>
      </div>
      <div className="panel p-4">
        {!data ? <Loading /> : (
          <DataTable<Alert>
            rows={data.items}
            columns={[
              { key: "title", header: "Alert", render: (r) => <div><div className="text-ink-100">{r.title}</div><div className="text-xs text-ink-500">{r.source}</div></div> },
              { key: "severity", header: "Severity", render: (r) => <Badge kind="severity" value={r.severity} /> },
              { key: "status", header: "Status", render: (r) => <Badge kind="status" value={r.status} /> },
              { key: "confidence", header: "Confidence", render: (r) => <ConfidenceBar value={r.confidence} /> },
              { key: "techniques", header: "ATT&CK", render: (r) => <span className="text-xs font-mono text-ink-400">{r.attack_techniques?.join(", ") || "—"}</span> },
              { key: "created_at", header: "Age", render: (r) => <span className="text-ink-400">{timeAgo(r.created_at)}</span> },
              {
                key: "actions", header: "", render: (r) => (
                  <div className="flex gap-1.5" onClick={(e) => e.stopPropagation()}>
                    {r.incident_id ? (
                      <button className="btn-ghost !py-1 !text-xs" onClick={() => router.push(`/incidents/${r.incident_id}`)}>View case</button>
                    ) : (
                      <>
                        {can("alert:write") && r.status === "new" && <button className="btn-ghost !py-1 !text-xs" onClick={() => act(r.id, "acknowledge")}>Ack</button>}
                        {can("incident:write") && <button className="btn-primary !py-1 !text-xs" onClick={() => act(r.id, "promote")}>→ Incident</button>}
                      </>
                    )}
                  </div>
                )
              },
            ]}
          />
        )}
      </div>
    </div>
  );
}
