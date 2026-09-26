"use client";

import { useState } from "react";
import { Download, FileText } from "lucide-react";
import { api, download } from "@/lib/api";
import { useApi, useApp } from "@/lib/store";
import { DataTable, ErrorState, PageHeader, Panel, Skeleton } from "@/components/ui";
import { PeriodPicker, ResultBanner, currentPeriod, useAction, useOpenInTenant } from "@/components/mssp";
import { num, titleCase } from "@/lib/ui";

interface UsageRow { tenant_id: string; tenant: string; slug: string; service_tier: string; region: string; [metric: string]: string | number }

export default function BillingPage() {
  const { canHome } = useApp();
  const openIn = useOpenInTenant();
  const [period, setPeriod] = useState(currentPeriod());
  const usage = useApi<{ period: string; metrics: Record<string, string>; customers: UsageRow[] }>(`/mssp/usage?period=${period}`);
  const action = useAction();
  const [reports, setReports] = useState<{ tenant: string; report_id: string; title: string; tenant_id?: string }[]>([]);

  const metrics = Object.entries(usage.data?.metrics || {});
  const totals = Object.fromEntries(metrics.map(([m]) => [m, (usage.data?.customers || []).reduce((a, r) => a + Number(r[m] || 0), 0)]));

  const csv = () => action.run(() => download(`/mssp/usage?period=${period}&format=csv`, `usage-${period}.csv`), `usage-${period}.csv downloaded.`);
  const generate = () => action.run(async () => {
    const res = await api.post<{ reports: { tenant: string; report_id: string; title: string }[] }>("/mssp/reports/service", { period });
    const byName = Object.fromEntries((usage.data?.customers || []).map((c) => [c.tenant, c.tenant_id]));
    setReports(res.reports.map((r) => ({ ...r, tenant_id: byName[r.tenant] })));
  }, "Service reports generated and stored in each customer's tenant, where their own users can read them.");

  return (
    <div>
      <PageHeader
        title="Usage & Billing"
        subtitle="Metered consumption per customer for invoicing, plus monthly managed-service reports."
        actions={<>
          <PeriodPicker value={period} onChange={setPeriod} />
          <button className="btn-ghost" onClick={csv} disabled={action.busy}><Download className="w-4 h-4" /> CSV</button>
          {canHome("mssp:portfolio") && <button className="btn-primary" onClick={generate} disabled={action.busy}><FileText className="w-4 h-4" /> Generate service reports</button>}
        </>}
      />
      <ResultBanner result={action.result} />

      {reports.length > 0 && (
        <Panel title={`Service reports · ${period}`} className="mb-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {reports.map((r) => (
              <button key={r.report_id} className="text-left text-sm border border-white/5 rounded-lg px-3 py-2 hover:border-cyan/30"
                onClick={() => r.tenant_id && openIn(r.tenant_id, "/reports")}>
                <div className="text-ink-100">{r.tenant}</div>
                <div className="text-xs text-ink-400">{r.title}</div>
              </button>
            ))}
          </div>
        </Panel>
      )}

      <Panel>
        {usage.error ? <ErrorState message={usage.error.message} /> : usage.loading && !usage.data ? <Skeleton rows={6} /> : (
          <>
            <DataTable<UsageRow & { id: string }>
              rows={(usage.data?.customers || []).map((r) => ({ ...r, id: r.tenant_id }))}
              empty="No customers in scope."
              columns={[
                { key: "tenant", header: "Customer", render: (r) => <div><div className="text-ink-100">{r.tenant}</div><div className="text-[10px] text-ink-500">{titleCase(String(r.service_tier))} · {String(r.region).toUpperCase()}</div></div> },
                ...metrics.map(([m, label]) => ({
                  key: m, header: titleCase(m), className: "tabular-nums text-right",
                  render: (r: UsageRow) => <span title={label}>{num(Number(r[m] || 0))}</span>,
                })),
              ]}
            />
            {!!usage.data?.customers.length && (
              <div className="flex flex-wrap gap-4 justify-end text-xs text-ink-400 mt-3 border-t border-white/5 pt-2">
                {metrics.map(([m]) => <span key={m}>{titleCase(m)}: <b className="text-ink-200 tabular-nums">{num(totals[m])}</b></span>)}
              </div>
            )}
          </>
        )}
        <p className="text-[11px] text-ink-500 mt-3">Counters are recorded as work happens (events ingested, alerts, incidents, agent runs, LLM tokens, reports); nothing is estimated. Response actions are not metered yet, so that column reads 0 (see Known Limitations).</p>
      </Panel>
    </div>
  );
}
