"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { qs } from "@/lib/api";
import { useApi, useLiveEvents } from "@/lib/store";
import type { SlaState } from "@/lib/types";
import { Badge, DataTable, ErrorState, PageHeader, Panel, Skeleton } from "@/components/ui";
import { SlaClock, useOpenInTenant } from "@/components/mssp";
import { timeAgo, titleCase } from "@/lib/ui";

interface Row {
  id: string; key: string; title: string; severity: string; status: string; created_at: string;
  owner_id: string | null; tenant: { id: string; name: string; slug: string; service_tier: string };
  sla: SlaState;
}

export default function UnifiedQueuePage() {
  const open = useOpenInTenant();
  const [severity, setSeverity] = useState("");
  const [sla, setSla] = useState("");
  const [tenant, setTenant] = useState("");
  const [page, setPage] = useState(1);
  const path = `/mssp/queue${qs({ severity, sla, tenant, page, page_size: 50 })}`;
  const { data, error, loading, reload } = useApi<{ items: Row[]; total: number; pages: number }>(path);
  const portfolio = useApi<{ customers: { id: string; name: string; slug: string }[] }>("/mssp/overview");

  useLiveEvents((ev) => {
    if (ev.type === "incident.created" || ev.type === "incident.updated") reload();
  });

  return (
    <div>
      <PageHeader
        title="Unified Queue"
        subtitle="Open incidents across all customers — SLA breaches first, then severity, then time remaining."
        actions={<button className="btn-ghost" onClick={reload}><RefreshCw className="w-4 h-4" /> Refresh</button>}
      />
      <Panel className="mb-3">
        <div className="flex flex-wrap gap-2">
          <select className="input !w-auto" value={tenant} onChange={(e) => { setTenant(e.target.value); setPage(1); }} aria-label="Customer">
            <option value="">All customers</option>
            {portfolio.data?.customers.map((c) => <option key={c.id} value={c.slug}>{c.name}</option>)}
          </select>
          <select className="input !w-auto" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }} aria-label="Severity">
            <option value="">All severities</option>
            {["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </select>
          <select className="input !w-auto" value={sla} onChange={(e) => { setSla(e.target.value); setPage(1); }} aria-label="SLA state">
            <option value="">Any SLA state</option>
            <option value="breached">Breached</option>
            <option value="at_risk">At risk</option>
            <option value="on_track">On track</option>
          </select>
          <span className="ml-auto text-xs text-ink-400 self-center">{data ? `${data.total} incidents` : ""}</span>
        </div>
      </Panel>
      <Panel>
        {error ? <ErrorState message={error.message} /> : loading && !data ? <Skeleton rows={8} /> : (
          <>
            <DataTable<Row>
              rows={data?.items || []}
              empty="Nothing open. Every customer queue is clear."
              onRow={(r) => open(r.tenant.id, `/incidents/${r.id}`)}
              columns={[
                { key: "tenant", header: "Customer", render: (r) => (
                  <div><div className="text-ink-100">{r.tenant.name}</div><div className="text-[10px] text-ink-500">{titleCase(r.tenant.service_tier)}</div></div>) },
                { key: "key", header: "Incident", render: (r) => (
                  <div className="max-w-md"><div className="font-mono text-xs text-cyan">{r.key}</div><div className="truncate">{r.title}</div></div>) },
                { key: "severity", header: "Severity", render: (r) => <Badge kind="severity" value={r.severity} /> },
                { key: "status", header: "Status", render: (r) => <Badge kind="status" value={r.status} /> },
                { key: "sla", header: "SLA", render: (r) => <SlaClock sla={r.sla} /> },
                { key: "owner", header: "Owner", render: (r) => r.owner_id ? <span className="text-xs">assigned</span> : <span className="text-xs text-amber">unassigned</span> },
                { key: "age", header: "Age", render: (r) => <span className="text-xs text-ink-400">{timeAgo(r.created_at)}</span> },
              ]}
            />
            {data && data.pages > 1 && (
              <div className="flex items-center justify-end gap-2 mt-3 text-xs">
                <button className="btn-ghost !py-1" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
                <span className="text-ink-400">Page {page} / {data.pages}</span>
                <button className="btn-ghost !py-1" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</button>
              </div>
            )}
          </>
        )}
      </Panel>
    </div>
  );
}
