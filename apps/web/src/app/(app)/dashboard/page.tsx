"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, ShieldAlert, Cpu, Boxes, Zap, Clock } from "lucide-react";
import { api } from "@/lib/api";
import { useApp, useEventStream } from "@/lib/store";
import { Chart } from "@/components/Chart";
import { Badge, Loading, Panel, PageHeader, StatTile } from "@/components/ui";
import { num, titleCase, timeAgo } from "@/lib/ui";

export default function DashboardPage() {
  const { mode } = useApp();
  const router = useRouter();
  const [ov, setOv] = useState<any>(null);
  const [trends, setTrends] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);

  async function load() {
    const [o, t] = await Promise.all([
      api.get<any>("/dashboard/overview"),
      api.get<any>("/dashboard/trends"),
    ]);
    setOv(o);
    setTrends(t);
  }
  useEffect(() => { load(); }, []);
  useEffect(() => {
    api.get<any>("/dashboard/live-events?limit=18").then((r) => setEvents(r.events)).catch(() => {});
  }, []);

  useEventStream(mode?.mode, (ev) => {
    if (ev.type === "event.ingested" || ev.type === "alert.created" || ev.type === "incident.created") {
      setEvents((prev) => [ev, ...prev].slice(0, 18));
    }
    if (ev.type === "incident.created" || ev.type === "action.executed") load();
  });

  if (!ov) return <Loading label="Loading SOC overview…" />;
  const k = ov.kpis;

  return (
    <div>
      <PageHeader
        title="SOC Overview"
        subtitle={`Live command center · scope ${ov.scope} · ${mode?.llm_strategy} AI`}
        actions={<Badge value={ov.scope === "DEMO" ? "info" : "critical"}>{ov.scope} DATA</Badge>}
      />

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-4">
        <StatTile label="Global Risk" value={num(k.global_risk_score, 1)} accent={k.global_risk_score > 70 ? "crit" : "cyan"} hint="0–100 blended" />
        <StatTile label="Active Incidents" value={num(k.active_incidents)} accent="cyan" onClick={() => router.push("/incidents")} hint="click to view" />
        <StatTile label="Critical" value={num(k.critical_incidents)} accent="crit" onClick={() => router.push("/incidents?severity=critical")} />
        <StatTile label="Alerts / 5m" value={num(k.alerts_last_5m)} accent="violet" onClick={() => router.push("/alerts")} hint={`${k.alerts_per_second}/s`} />
        <StatTile label="Automation" value={k.automation_success_rate != null ? `${Math.round(k.automation_success_rate * 100)}%` : "—"} accent="teal" hint="agent success" />
        <StatTile label="Pending Approvals" value={num(k.pending_approvals)} accent="amber" onClick={() => router.push("/approvals")} />
      </div>

      {/* Second KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <MiniStat icon={<Clock className="w-4 h-4" />} label="MTTA" value={k.mtta_minutes != null ? `${k.mtta_minutes}m` : "—"} />
        <MiniStat icon={<Clock className="w-4 h-4" />} label="MTTI" value={k.mtti_minutes != null ? `${k.mtti_minutes}m` : "—"} />
        <MiniStat icon={<Clock className="w-4 h-4" />} label="MTTR" value={k.mttr_minutes != null ? `${k.mttr_minutes}m` : "—"} />
        <MiniStat icon={<Activity className="w-4 h-4" />} label="Analyst Workload" value={num(k.analyst_workload)} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Incident trend */}
        <Panel title="Incident & Risk Trend" className="xl:col-span-2">
          <Chart
            height={260}
            option={{
              tooltip: { trigger: "axis" },
              legend: { data: ["Incidents", "Peak Risk"], textStyle: { color: "#9fb3d1" }, top: 0 },
              xAxis: { type: "category", data: (trends?.incident_trend || []).map((d: any) => d.date.slice(5)) },
              yAxis: [{ type: "value" }, { type: "value", max: 100 }],
              series: [
                { name: "Incidents", type: "bar", data: (trends?.incident_trend || []).map((d: any) => d.incidents), itemStyle: { color: "#22d3ee", borderRadius: [3, 3, 0, 0] } },
                { name: "Peak Risk", type: "line", yAxisIndex: 1, smooth: true, data: (trends?.incident_trend || []).map((d: any) => d.risk), lineStyle: { color: "#f43f5e" }, itemStyle: { color: "#f43f5e" } },
              ],
            }}
          />
        </Panel>

        {/* ATT&CK tactics */}
        <Panel title="ATT&CK Tactic Distribution">
          {ov.attack_tactics.length ? (
            <Chart
              height={260}
              onEvents={{ click: (p: any) => router.push(`/incidents`) }}
              option={{
                tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
                legend: { type: "scroll", orient: "vertical", right: 4, top: "middle",
                  textStyle: { color: "#9fb3d1", fontSize: 10 }, itemWidth: 8, itemHeight: 8 },
                series: [{
                  type: "pie", radius: ["42%", "68%"], center: ["32%", "52%"],
                  itemStyle: { borderColor: "#0a0f1c", borderWidth: 2 },
                  label: { show: false },
                  emphasis: { label: { show: true, fontSize: 12, color: "#e6f0ff" } },
                  data: ov.attack_tactics.map((t: any) => ({ name: t.tactic, value: t.count })),
                }],
              }}
            />
          ) : <div className="text-ink-500 text-sm py-16 text-center">No active tactics.</div>}
        </Panel>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mt-4">
        {/* Live event stream */}
        <Panel title="Live Event Stream" actions={<Badge value="info">real-time</Badge>}>
          <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1">
            {events.map((e, i) => (
              <div key={i} className="flex items-center gap-2 text-xs animate-streamdown border-b border-white/5 pb-1.5">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${e.type === "incident.created" ? "bg-crit" : e.type === "alert.created" ? "bg-amber" : "bg-teal"}`} />
                <span className="text-ink-300 truncate flex-1">
                  {e.type === "incident.created" ? `Incident: ${e.title}` : e.type === "alert.created" ? e.title : `${titleCase(e.activity || e.type)} · ${e.host || e.source || ""}`}
                </span>
                {e.simulated && <span className="text-[9px] text-amber">SIM</span>}
              </div>
            ))}
            {!events.length && <div className="text-ink-500 text-sm py-8 text-center">Awaiting events…</div>}
          </div>
        </Panel>

        {/* Severity distribution */}
        <Panel title="Active by Severity">
          <Chart
            height={220}
            onEvents={{ click: (p: any) => router.push(`/incidents?severity=${p.name}`) }}
            option={{
              tooltip: {},
              xAxis: { type: "category", data: ov.severity_distribution.map((s: any) => titleCase(s.key)) },
              yAxis: { type: "value" },
              series: [{
                type: "bar", data: ov.severity_distribution.map((s: any) => ({
                  value: s.count,
                  itemStyle: { color: sevColor(s.key), borderRadius: [3, 3, 0, 0] },
                })),
              }],
            }}
          />
        </Panel>

        {/* Health */}
        <Panel title="Platform Health">
          <div className="space-y-3">
            <HealthRow icon={<Cpu className="w-4 h-4 text-violet" />} label="AI Providers" items={ov.ai_health.map((p: any) => ({ name: p.name, state: p.health }))} />
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-ink-300"><Boxes className="w-4 h-4 text-cyan" /> Connectors</span>
              <span className="text-ink-200">{ov.connector_health.enabled}/{ov.connector_health.total} enabled</span>
            </div>
            <div>
              <div className="label mb-1.5">Top Risky Identities</div>
              {ov.top_risky_entities.map((e: any) => (
                <div key={e.value} className="flex items-center justify-between text-xs py-1 border-b border-white/5 last:border-0">
                  <span className="text-ink-300 truncate">{e.display}</span>
                  <span className="text-amber tabular-nums">{e.risk}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function MiniStat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="panel px-4 py-3 flex items-center gap-3">
      <div className="text-cyan">{icon}</div>
      <div>
        <div className="label">{label}</div>
        <div className="text-lg font-bold text-ink-100 tabular-nums">{value}</div>
      </div>
    </div>
  );
}

function HealthRow({ icon, label, items }: { icon: React.ReactNode; label: string; items: any[] }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="flex items-center gap-2 text-ink-300">{icon} {label}</span>
      <div className="flex gap-1">
        {items.map((it, i) => (
          <span key={i} title={`${it.name}: ${it.state}`} className={`w-2 h-2 rounded-full ${it.state === "healthy" ? "bg-teal" : it.state === "not_configured" ? "bg-ink-500" : it.state === "degraded" ? "bg-amber" : "bg-crit"}`} />
        ))}
      </div>
    </div>
  );
}

function sevColor(s: string): string {
  return { critical: "#f43f5e", high: "#f59e0b", medium: "#22d3ee", low: "#2dd4bf", info: "#4a5a78" }[s] || "#22d3ee";
}
