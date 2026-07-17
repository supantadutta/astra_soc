"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Badge, Loading, PageHeader, Panel } from "@/components/ui";
import { EVIDENCE_KIND_META, cx, fmtDate } from "@/lib/ui";

export default function TimelinePage() {
  const [incidents, setIncidents] = useState<any[]>([]);
  const [sel, setSel] = useState<string>("");
  const [detail, setDetail] = useState<any>(null);

  useEffect(() => {
    api.get<any>("/incidents?page_size=50").then((r) => {
      setIncidents(r.items);
      if (r.items[0]) setSel(r.items[0].id);
    });
  }, []);
  useEffect(() => { if (sel) api.get<any>(`/incidents/${sel}`).then(setDetail); }, [sel]);

  return (
    <div>
      <PageHeader title="Evidence Timeline" subtitle="Cross-referenced chronology with epistemic labelling" />
      <div className="mb-4">
        <select className="input max-w-xl" value={sel} onChange={(e) => setSel(e.target.value)}>
          {incidents.map((i) => <option key={i.id} value={i.id}>{i.key} — {i.title}</option>)}
        </select>
      </div>

      {!detail ? <Loading /> : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Panel title="Timeline" className="lg:col-span-2">
            <div className="relative pl-6">
              <div className="absolute left-2 top-1 bottom-1 w-px bg-white/10" />
              {detail.timeline.map((t: any) => (
                <div key={t.id} className="relative mb-4">
                  <span className={cx("absolute -left-[19px] top-1 w-3 h-3 rounded-full border-2 border-navy-800",
                    t.category === "action" ? "bg-amber" : t.category === "note" ? "bg-cyan" : "bg-teal")} />
                  <div className="text-sm text-ink-100">{t.title}</div>
                  <div className="text-xs text-ink-500">{fmtDate(t.occurred_at)} · {t.category}
                    {t.evidence_id && <span className="text-cyan"> · linked evidence</span>}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="Evidence Legend & Items">
            <div className="space-y-1.5 mb-3">
              {Object.entries(EVIDENCE_KIND_META).map(([k, m]) => (
                <div key={k} className="flex items-center gap-2 text-xs"><span className={cx("chip", m.color)}>{m.label}</span><span className="text-ink-500">{m.note}</span></div>
              ))}
            </div>
            <Link href={`/incidents/${sel}`} className="btn-primary w-full">Open full workspace →</Link>
          </Panel>
        </div>
      )}
    </div>
  );
}
