"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useApp, useEventStream } from "@/lib/store";
import { Chart } from "@/components/Chart";
import { num, titleCase } from "@/lib/ui";

/** Fullscreen SOC wallboard — no chrome, giant KPIs, live stream. */
export default function WallboardPage() {
  return <Board />;
}

function Board() {
  const { mode } = useApp();
  const [ov, setOv] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [clock, setClock] = useState("");

  async function load() { setOv(await api.get<any>("/dashboard/overview")); }
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    const c = setInterval(() => setClock(new Date().toLocaleTimeString()), 1000);
    return () => { clearInterval(t); clearInterval(c); };
  }, []);

  useEventStream(mode?.mode, (ev) => {
    if (["event.ingested", "alert.created", "incident.created"].includes(ev.type)) {
      setEvents((prev) => [ev, ...prev].slice(0, 12));
    }
  });

  if (!ov) return <div className="min-h-screen flex items-center justify-center text-cyan text-xl animate-pulseGlow">ASTRASOC WALLBOARD</div>;
  const k = ov.kpis;

  return (
    <div className="min-h-screen p-6 flex flex-col relative z-10">
      <header className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <span className="text-2xl font-black tracking-widest text-cyan">ASTRASOC</span>
          <span className={`chip ${mode?.is_live ? "text-crit border-crit/50 bg-crit/10" : "text-cyan border-cyan/40 bg-cyan/10"} !text-sm !px-3 !py-1`}>{mode?.mode}</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-3xl font-mono tabular-nums text-ink-100">{clock}</span>
          <Link href="/dashboard" className="btn-ghost">Exit</Link>
        </div>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <Big label="GLOBAL RISK" value={num(k.global_risk_score, 1)} color={k.global_risk_score > 70 ? "text-crit" : "text-cyan"} />
        <Big label="ACTIVE INCIDENTS" value={num(k.active_incidents)} color="text-cyan" />
        <Big label="CRITICAL" value={num(k.critical_incidents)} color="text-crit" />
        <Big label="PENDING APPROVALS" value={num(k.pending_approvals)} color="text-amber" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 flex-1">
        <div className="panel p-4 lg:col-span-2">
          <div className="label mb-2">ATT&CK Tactic Distribution</div>
          <Chart height={340} option={{
            tooltip: {},
            xAxis: { type: "category", data: ov.attack_tactics.map((t: any) => t.tactic), axisLabel: { rotate: 25, color: "#6f83a6" } },
            yAxis: { type: "value" },
            series: [{ type: "bar", data: ov.attack_tactics.map((t: any) => t.count), itemStyle: { color: "#a78bfa", borderRadius: [4, 4, 0, 0] } }],
          }} />
        </div>
        <div className="panel p-4 overflow-hidden">
          <div className="label mb-2">Live Stream</div>
          <div className="space-y-2">
            {events.map((e, i) => (
              <div key={i} className="text-sm animate-streamdown flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${e.type === "incident.created" ? "bg-crit animate-pulseGlow" : e.type === "alert.created" ? "bg-amber" : "bg-teal"}`} />
                <span className="text-ink-200 truncate">{e.title || `${titleCase(e.activity || e.type)} · ${e.host || e.source || ""}`}</span>
              </div>
            ))}
            {!events.length && <div className="text-ink-500">Awaiting telemetry…</div>}
          </div>
        </div>
      </div>
    </div>
  );
}

function Big({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="panel p-6 text-center">
      <div className="label">{label}</div>
      <div className={`text-6xl font-black tabular-nums mt-2 ${color}`}>{value}</div>
    </div>
  );
}
