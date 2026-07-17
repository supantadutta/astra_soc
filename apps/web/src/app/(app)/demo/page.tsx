"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Pause, Play, RotateCcw, Rocket, Gauge } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Loading, PageHeader, Panel } from "@/components/ui";
import { titleCase } from "@/lib/ui";

export default function DemoPage() {
  const router = useRouter();
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [gen, setGen] = useState<any>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const [s, g] = await Promise.all([api.get<any>("/demo/scenarios"), api.get<any>("/demo/generator")]);
    setScenarios(s.scenarios); setGen(g);
  }
  useEffect(() => { load(); }, []);

  async function launch(key: string) {
    try { const inc = await api.post<any>(`/demo/scenarios/${key}/launch`); setToast(`Launched scenario. Incident ${inc.key} created.`); router.push(`/incidents/${inc.id}`); }
    catch (e: any) { setToast(e.message); }
  }
  async function reset() {
    setBusy(true);
    try { await api.post("/demo/reset"); setToast("Demo data reset and reseeded (live data untouched)."); }
    catch (e: any) { setToast(e.message); } finally { setBusy(false); }
  }
  async function control(patch: any) {
    const g = await api.post<any>("/demo/generator", patch); setGen(g);
  }

  if (!gen) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Demo Control Center"
        subtitle="Launch, pause, speed and reset simulated SOC activity"
        actions={<button className="btn-danger" disabled={busy} onClick={reset}><RotateCcw className="w-4 h-4" /> Reset & reseed</button>}
      />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}

      <Panel title="Event Generator" className="mb-4">
        <div className="flex flex-wrap items-center gap-4">
          <Badge value={gen.paused ? "not_configured" : "healthy"}>{gen.paused ? "paused" : "running"}</Badge>
          <span className="text-sm text-ink-400">{gen.events} events generated · {gen.aps}/s</span>
          <button className="btn-ghost" onClick={() => control({ paused: !gen.paused })}>
            {gen.paused ? <><Play className="w-4 h-4" /> Resume</> : <><Pause className="w-4 h-4" /> Pause</>}
          </button>
          <div className="flex items-center gap-2">
            <Gauge className="w-4 h-4 text-cyan" />
            {[0.5, 1, 2, 4].map((s) => (
              <button key={s} onClick={() => control({ speed: s })} className={`btn-ghost !py-1 !text-xs ${gen.speed === s ? "!text-cyan !border-cyan/40" : ""}`}>{s}×</button>
            ))}
          </div>
        </div>
      </Panel>

      <Panel title={`Attack Scenarios (${scenarios.length})`}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {scenarios.map((s) => (
            <div key={s.key} className="rounded-lg border border-white/5 p-3 hover:border-cyan/30 transition-colors">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm text-ink-100 font-medium">{s.title}</span>
                <Badge kind="severity" value={s.severity} />
              </div>
              <p className="text-xs text-ink-400">{s.summary}</p>
              <div className="flex flex-wrap gap-1 mt-2">
                {s.attack_techniques?.slice(0, 4).map((t: string) => <span key={t} className="chip text-ink-400 border-white/10 font-mono text-[10px]">{t}</span>)}
              </div>
              <button className="btn-primary mt-2 !py-1 !text-xs" onClick={() => launch(s.key)}><Rocket className="w-3.5 h-3.5" /> Launch</button>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
