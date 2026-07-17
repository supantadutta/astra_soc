"use client";

import { useEffect, useState } from "react";
import { FileText } from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, DataTable, Loading, PageHeader, Panel } from "@/components/ui";
import { fmtDate, titleCase } from "@/lib/ui";

export default function ReportsPage() {
  const { can } = useApp();
  const [types, setTypes] = useState<string[]>([]);
  const [data, setData] = useState<any>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    const [t, r] = await Promise.all([api.get<any>("/reports/types"), api.get<any>("/reports?page_size=30")]);
    setTypes(t.types); setData(r);
  }
  useEffect(() => { load(); }, []);

  async function gen(t: string) {
    setBusy(t);
    try { await api.post("/reports", { report_type: t }); setToast(`Generated ${titleCase(t)}.`); load(); }
    catch (e: any) { setToast(e.message); } finally { setBusy(null); }
  }

  return (
    <div>
      <PageHeader title="Reports" subtitle="Evidence-cited reports · facts vs AI inferences distinguished · export JSON/CSV/HTML/PDF" />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}

      {can("report:generate") && (
        <Panel title="Generate" className="mb-4">
          <div className="flex flex-wrap gap-2">
            {types.map((t) => (
              <button key={t} className="btn-ghost !text-xs" disabled={busy === t} onClick={() => gen(t)}>
                <FileText className="w-3.5 h-3.5" /> {busy === t ? "Generating…" : titleCase(t)}
              </button>
            ))}
          </div>
        </Panel>
      )}

      <Panel title="Generated Reports">
        {!data ? <Loading /> : (
          <DataTable
            rows={data.items}
            columns={[
              { key: "title", header: "Report", render: (r: any) => <span className="text-ink-100">{r.title}</span> },
              { key: "report_type", header: "Type", render: (r: any) => <Badge value="info">{titleCase(r.report_type)}</Badge> },
              { key: "data_scope", header: "Scope", render: (r: any) => <Badge value={r.data_scope === "DEMO" ? "info" : "critical"}>{r.data_scope}</Badge> },
              { key: "created_at", header: "Created", render: (r: any) => <span className="text-ink-400 text-xs">{fmtDate(r.created_at)}</span> },
              {
                key: "export", header: "Export", render: (r: any) => (
                  <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                    {["json", "csv", "html", "pdf"].map((f) => (
                      <a key={f} className="btn-ghost !py-0.5 !px-1.5 !text-[10px]" href={`/api/v1/reports/${r.id}/export?format=${f}`} target="_blank" rel="noreferrer">{f.toUpperCase()}</a>
                    ))}
                  </div>
                )
              },
            ]}
          />
        )}
      </Panel>
    </div>
  );
}
