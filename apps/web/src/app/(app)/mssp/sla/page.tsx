"use client";

import { useState } from "react";
import { useApi } from "@/lib/store";
import { DataTable, ErrorState, PageHeader, Panel, Skeleton, StatTile } from "@/components/ui";
import { PeriodPicker, currentPeriod, fmtMinutes, pct } from "@/components/mssp";
import { cx, titleCase } from "@/lib/ui";

interface Row {
  tenant_id: string; tenant: string; slug: string; service_tier: string; incidents: number;
  by_severity: Record<string, number>; ack_compliance: number | null; resolve_compliance: number | null;
  ack_measured: number; resolve_measured: number; mtta_minutes: number | null; mttr_minutes: number | null;
  open_breaches: number;
}

function tone(v: number | null) {
  if (v === null) return "text-ink-500";
  return v >= 0.95 ? "text-teal" : v >= 0.85 ? "text-amber" : "text-crit";
}

export default function SlaPage() {
  const [period, setPeriod] = useState(currentPeriod());
  const { data, error, loading } = useApi<{ period: string; customers: Row[] }>(`/mssp/sla?period=${period}`);
  const rows = data?.customers || [];
  const measured = (k: "ack" | "resolve") => rows.reduce((a, r) => a + (r[`${k}_measured`] || 0), 0);
  const weighted = (k: "ack" | "resolve") => {
    const total = measured(k);
    if (!total) return null;
    return rows.reduce((a, r) => a + (r[`${k}_compliance`] ?? 0) * r[`${k}_measured`], 0) / total;
  };

  return (
    <div>
      <PageHeader
        title="SLA Compliance"
        subtitle="Contractual acknowledgement and resolution targets per customer (tier defaults plus contract overrides)."
        actions={<PeriodPicker value={period} onChange={setPeriod} />}
      />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <StatTile label="Ack compliance" value={pct(weighted("ack"))} hint={`${measured("ack")} measured`} accent="teal" />
        <StatTile label="Resolve compliance" value={pct(weighted("resolve"))} hint={`${measured("resolve")} measured`} accent="teal" />
        <StatTile label="Incidents in period" value={rows.reduce((a, r) => a + r.incidents, 0)} />
        <StatTile label="Open breaches" value={rows.reduce((a, r) => a + r.open_breaches, 0)} accent="crit" />
      </div>
      <Panel>
        {error ? <ErrorState message={error.message} /> : loading && !data ? <Skeleton rows={6} /> : (
          <DataTable<Row & { id: string }>
            rows={rows.map((r) => ({ ...r, id: r.tenant_id }))}
            empty="No customers in scope."
            columns={[
              { key: "tenant", header: "Customer", render: (r) => <div><div className="text-ink-100">{r.tenant}</div><div className="text-[10px] text-ink-500">{titleCase(r.service_tier)}</div></div> },
              { key: "incidents", header: "Incidents" },
              { key: "ack", header: "Ack SLA", render: (r) => <span className={cx("tabular-nums font-semibold", tone(r.ack_compliance))}>{pct(r.ack_compliance)} <span className="text-[10px] text-ink-500 font-normal">({r.ack_measured})</span></span> },
              { key: "res", header: "Resolve SLA", render: (r) => <span className={cx("tabular-nums font-semibold", tone(r.resolve_compliance))}>{pct(r.resolve_compliance)} <span className="text-[10px] text-ink-500 font-normal">({r.resolve_measured})</span></span> },
              { key: "mtta", header: "MTTA", render: (r) => fmtMinutes(r.mtta_minutes) },
              { key: "mttr", header: "MTTR", render: (r) => fmtMinutes(r.mttr_minutes) },
              { key: "breach", header: "Open breaches", render: (r) => <span className={r.open_breaches ? "text-crit font-semibold" : ""}>{r.open_breaches}</span> },
            ]}
          />
        )}
        <p className="text-[11px] text-ink-500 mt-3">
          Covers incidents created in the period. A clock is counted once it is decided: met, or breached (including open
          incidents already past due). Clocks still running are excluded; “—” means nothing is decided yet, not 100%.
        </p>
      </Panel>
    </div>
  );
}
