"use client";

import { useEffect, useState } from "react";
import { api, qs } from "@/lib/api";
import { Badge, DataTable, Loading, PageHeader } from "@/components/ui";
import { fmtDate, titleCase } from "@/lib/ui";

export default function ThreatIntelPage() {
  const [data, setData] = useState<any>(null);
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { api.get<any>(`/threat-intel${qs({ ioc_type: type, q, page_size: 50 })}`).then(setData); }, [type, q]);

  return (
    <div>
      <PageHeader title="Threat Intelligence" subtitle="Indicators from MISP, VirusTotal, TAXII and manual sources" />
      <div className="flex flex-wrap gap-2 mb-4">
        <input className="input max-w-xs" placeholder="Search indicators…" value={q} onChange={(e) => setQ(e.target.value)} />
        {["", "ip", "domain", "hash", "url"].map((t) => <button key={t} onClick={() => setType(t)} className={`btn-ghost !text-xs ${type === t ? "!text-cyan !border-cyan/40" : ""}`}>{t ? titleCase(t) : "All"}</button>)}
      </div>
      <div className="panel p-4">
        {!data ? <Loading /> : (
          <DataTable
            rows={data.items}
            columns={[
              { key: "ioc_type", header: "Type", render: (r: any) => <Badge value="info">{r.ioc_type}</Badge> },
              { key: "value", header: "Indicator", render: (r: any) => <span className="font-mono text-ink-100">{r.value}</span> },
              { key: "threat_type", header: "Threat", render: (r: any) => titleCase(r.threat_type || "—") },
              { key: "confidence", header: "Conf", render: (r: any) => `${Math.round(r.confidence * 100)}%` },
              { key: "source", header: "Source", render: (r: any) => <span className="text-ink-400">{r.source}</span> },
              { key: "tlp", header: "TLP", render: (r: any) => <Badge kind="severity" value={r.tlp === "red" ? "critical" : r.tlp === "amber" ? "high" : "low"}>{r.tlp}</Badge> },
              { key: "last_seen", header: "Last seen", render: (r: any) => <span className="text-ink-400 text-xs">{fmtDate(r.last_seen)}</span> },
            ]}
          />
        )}
      </div>
    </div>
  );
}
