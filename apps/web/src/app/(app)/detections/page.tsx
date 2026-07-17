"use client";

import { useEffect, useState } from "react";
import { Radar, Play } from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, DataTable, Loading, Modal, PageHeader } from "@/components/ui";
import { fmtDate, titleCase } from "@/lib/ui";

export default function DetectionsPage() {
  const { can } = useApp();
  const [data, setData] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);
  const [toast, setToast] = useState<string | null>(null);

  async function load() { setData(await api.get<any>("/detections?page_size=50")); }
  useEffect(() => { load(); }, []);

  async function replay(id: string) {
    try { const r = await api.post<any>(`/detections/${id}/replay`); setToast(`Replay: ${r.matches} match(es) over ${r.scanned} events.`); }
    catch (e: any) { setToast(e.message); }
  }

  return (
    <div>
      <PageHeader title="Detection Engineering" subtitle="Sigma rules · deterministic matchers · replay · never auto-deploy AI rules" />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}
      <div className="panel p-4">
        {!data ? <Loading /> : (
          <DataTable
            rows={data.items}
            onRow={(r: any) => setDetail(r)}
            empty="No detection rules yet. Author one from an incident's TTPs."
            columns={[
              { key: "name", header: "Rule", render: (r: any) => <span className="flex items-center gap-2 text-ink-100"><Radar className="w-4 h-4 text-cyan" /> {r.name}</span> },
              { key: "severity", header: "Severity", render: (r: any) => <Badge kind="severity" value={r.severity} /> },
              { key: "status", header: "Status", render: (r: any) => <Badge kind="status" value={r.status} /> },
              { key: "ai_generated", header: "Origin", render: (r: any) => <Badge value={r.ai_generated ? "info" : "healthy"}>{r.ai_generated ? "AI-drafted" : "authored"}</Badge> },
              { key: "trigger_count", header: "Triggers", render: (r: any) => r.trigger_count || 0 },
              { key: "actions", header: "", render: (r: any) => can("detection:read") && <button className="btn-ghost !py-1 !text-xs" onClick={(e) => { e.stopPropagation(); replay(r.id); }}><Play className="w-3.5 h-3.5" /> Replay</button> },
            ]}
          />
        )}
      </div>

      <Modal open={!!detail} onClose={() => setDetail(null)} title={detail?.name || "Rule"} wide>
        {detail && (
          <div className="space-y-2 text-sm">
            <div className="flex gap-2"><Badge kind="severity" value={detail.severity} /><Badge kind="status" value={detail.status} /></div>
            <p className="text-ink-400">{detail.description}</p>
            <div className="label">ATT&CK: <span className="font-mono text-ink-300">{detail.attack_techniques?.join(", ") || "—"}</span></div>
            <div className="label mt-2">Sigma</div>
            <pre className="text-xs bg-navy-900 rounded-lg p-3 overflow-x-auto text-ink-300">{detail.sigma || "(no sigma body)"}</pre>
            <div className="label mt-2">Matcher (deterministic)</div>
            <pre className="text-xs bg-navy-900 rounded-lg p-3 overflow-x-auto text-ink-300">{JSON.stringify(detail.matcher, null, 2)}</pre>
          </div>
        )}
      </Modal>
    </div>
  );
}
