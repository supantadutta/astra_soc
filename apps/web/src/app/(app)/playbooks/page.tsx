"use client";

import { useEffect, useState } from "react";
import { Workflow, Play, ChevronRight } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Loading, PageHeader, Panel } from "@/components/ui";
import { fmtDate, titleCase } from "@/lib/ui";

export default function PlaybooksPage() {
  const [playbooks, setPlaybooks] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);

  async function load() {
    const [p, r] = await Promise.all([api.get<any>("/playbooks"), api.get<any>("/playbooks/runs?page_size=15")]);
    setPlaybooks(p.items); setRuns(r.items);
  }
  useEffect(() => { load(); }, []);
  async function open(key: string) { setDetail(await api.get<any>(`/playbooks/${key}`)); }

  return (
    <div>
      <PageHeader title="Automation Playbooks" subtitle="Durable workflows · survive restart, approval delay, worker failure" />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Panel title="Playbooks">
          <div className="space-y-2">
            {playbooks.map((p) => (
              <button key={p.id} onClick={() => open(p.key)} className="w-full text-left rounded-lg border border-white/5 p-3 hover:border-cyan/30 transition-colors">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-sm text-ink-100"><Workflow className="w-4 h-4 text-cyan" /> {p.name}</span>
                  <Badge value={p.enabled ? "healthy" : "not_configured"}>{p.enabled ? "enabled" : "off"}</Badge>
                </div>
                <p className="text-xs text-ink-400 mt-1">{p.description}</p>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title="Recent Workflow Runs">
          <div className="space-y-2">
            {runs.map((r) => (
              <div key={r.id} className="rounded-lg border border-white/5 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-ink-100">{titleCase(r.playbook_key)}</span>
                  <Badge kind="status" value={r.status} />
                </div>
                <div className="text-xs text-ink-500 mt-1">{r.step_history?.length || 0} steps · {fmtDate(r.created_at)}</div>
              </div>
            ))}
            {!runs.length && <div className="text-ink-500 text-sm py-6 text-center">No runs yet. Playbooks auto-trigger on matching incidents.</div>}
          </div>
        </Panel>
      </div>

      {detail && (
        <Panel title={`${detail.name} — Steps`} className="mt-4">
          <div className="flex flex-wrap items-center gap-2">
            {(detail.graph?.steps || []).map((s: any, i: number) => (
              <div key={s.id} className="flex items-center gap-2">
                <span className={`chip ${s.type === "approval" ? "text-amber border-amber/40 bg-amber/10" : s.type === "response_action" ? "text-crit border-crit/40 bg-crit/10" : "text-ink-200 border-white/10 bg-white/5"}`}>
                  {titleCase(s.type)}{s.name ? `: ${s.name}` : ""}
                </span>
                {i < detail.graph.steps.length - 1 && <ChevronRight className="w-3.5 h-3.5 text-ink-500" />}
              </div>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}
