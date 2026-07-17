"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, qs } from "@/lib/api";
import { Badge, DataTable, Loading, PageHeader, ConfidenceBar } from "@/components/ui";
import type { Incident, Page } from "@/lib/types";
import { fmtDate, timeAgo, titleCase } from "@/lib/ui";

const SEVERITIES = ["", "critical", "high", "medium", "low"];
const STATUSES = ["", "new", "triaged", "investigating", "contained", "resolved", "closed"];

export default function IncidentsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [data, setData] = useState<Page<Incident> | null>(null);
  const [severity, setSeverity] = useState(params.get("severity") || "");
  const [status, setStatus] = useState(params.get("status") || "");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.get<Page<Incident>>(`/incidents${qs({ severity, status, q, page, page_size: 20 })}`).then(setData);
  }, [severity, status, q, page]);

  return (
    <div>
      <PageHeader title="Incidents" subtitle={`${data?.total ?? "—"} cases in scope`} />
      <div className="flex flex-wrap gap-2 mb-4">
        <input className="input max-w-xs" placeholder="Search incidents…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <select className="input max-w-[160px]" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }}>
          {SEVERITIES.map((s) => <option key={s} value={s}>{s ? titleCase(s) : "All severities"}</option>)}
        </select>
        <select className="input max-w-[160px]" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          {STATUSES.map((s) => <option key={s} value={s}>{s ? titleCase(s) : "All statuses"}</option>)}
        </select>
      </div>

      <div className="panel p-4">
        {!data ? <Loading /> : (
          <DataTable<Incident>
            rows={data.items}
            onRow={(r) => router.push(`/incidents/${r.id}`)}
            columns={[
              { key: "key", header: "ID", render: (r) => <span className="font-mono text-cyan">{r.key}</span>, className: "w-24" },
              { key: "title", header: "Title", render: (r) => <span className="text-ink-100">{r.title}</span> },
              { key: "severity", header: "Severity", render: (r) => <Badge kind="severity" value={r.severity} /> },
              { key: "status", header: "Status", render: (r) => <Badge kind="status" value={r.status} /> },
              { key: "confidence", header: "Confidence", render: (r) => <ConfidenceBar value={r.confidence} /> },
              { key: "business_risk", header: "Risk", render: (r) => <span className="tabular-nums text-amber">{Math.round(r.business_risk)}</span>, className: "w-16" },
              { key: "created_at", header: "Age", render: (r) => <span className="text-ink-400">{timeAgo(r.created_at)}</span>, className: "w-20" },
            ]}
          />
        )}
        {data && data.pages > 1 && (
          <div className="flex items-center justify-between mt-3 text-sm text-ink-400">
            <span>Page {data.page} of {data.pages}</span>
            <div className="flex gap-2">
              <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Prev</button>
              <button className="btn-ghost" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>Next</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
