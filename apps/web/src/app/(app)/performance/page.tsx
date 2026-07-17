"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Chart } from "@/components/Chart";
import { Loading, PageHeader, Panel, StatTile } from "@/components/ui";
import { num } from "@/lib/ui";

export default function PerformancePage() {
  const [ov, setOv] = useState<any>(null);
  const [runs, setRuns] = useState<any>(null);

  useEffect(() => {
    api.get<any>("/dashboard/overview").then(setOv);
    api.get<any>("/agents/runs?page_size=100").then(setRuns);
  }, []);

  if (!ov) return <Loading />;
  const k = ov.kpis;
  const agentStats: Record<string, { total: number; ok: number }> = {};
  (runs?.items || []).forEach((r: any) => {
    agentStats[r.agent_key] = agentStats[r.agent_key] || { total: 0, ok: 0 };
    agentStats[r.agent_key].total++;
    if (r.status === "succeeded") agentStats[r.agent_key].ok++;
  });

  return (
    <div>
      <PageHeader title="Analyst Performance" subtitle="Team throughput, response times and automation assist" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <StatTile label="MTTA" value={k.mtta_minutes != null ? `${k.mtta_minutes}m` : "—"} accent="cyan" hint="mean time to acknowledge" />
        <StatTile label="MTTI" value={k.mtti_minutes != null ? `${k.mtti_minutes}m` : "—"} accent="violet" hint="mean time to investigate" />
        <StatTile label="MTTR" value={k.mttr_minutes != null ? `${k.mttr_minutes}m` : "—"} accent="teal" hint="mean time to respond" />
        <StatTile label="Automation Assist" value={k.automation_success_rate != null ? `${Math.round(k.automation_success_rate * 100)}%` : "—"} accent="amber" hint="agent success rate" />
      </div>

      <Panel title="Agent Success by Specialist">
        <Chart
          height={300}
          option={{
            tooltip: {},
            xAxis: { type: "category", data: Object.keys(agentStats), axisLabel: { rotate: 30, color: "#6f83a6", fontSize: 9 } },
            yAxis: { type: "value", max: 1 },
            series: [{
              type: "bar",
              data: Object.values(agentStats).map((s) => ({ value: s.total ? s.ok / s.total : 0 })),
              itemStyle: { color: "#a78bfa", borderRadius: [3, 3, 0, 0] },
            }],
          }}
        />
      </Panel>
    </div>
  );
}
