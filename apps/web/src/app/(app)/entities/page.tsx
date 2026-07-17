"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge, DataTable, Loading, PageHeader, Panel } from "@/components/ui";
import { EntityGraph } from "@/components/EntityGraph";
import { titleCase } from "@/lib/ui";

export default function EntitiesPage() {
  const [graph, setGraph] = useState<any>(null);
  const [list, setList] = useState<any>(null);
  const [kind, setKind] = useState("");

  useEffect(() => { api.get<any>("/entities/graph").then(setGraph); }, []);
  useEffect(() => { api.get<any>(`/entities${kind ? `?kind=${kind}` : ""}`).then(setList); }, [kind]);

  return (
    <div>
      <PageHeader title="Entity Graph" subtitle="Enriched users, hosts, IPs, domains and their relationships" />
      <Panel title="Relationship Graph" className="mb-4">
        {graph ? <EntityGraph nodes={graph.nodes.map((n: any) => ({ id: n.id, label: n.label, kind: n.kind, criticality: n.criticality }))} edges={graph.edges} height={460} /> : <Loading />}
      </Panel>
      <Panel title="Entities">
        <div className="flex gap-2 mb-3">
          {["", "user", "host", "ip", "domain", "account", "cloud_resource", "vulnerability"].map((k) => (
            <button key={k} onClick={() => setKind(k)} className={`btn-ghost !text-xs ${kind === k ? "!text-cyan !border-cyan/40" : ""}`}>{k ? titleCase(k) : "All"}</button>
          ))}
        </div>
        {!list ? <Loading /> : (
          <DataTable
            rows={list.items}
            columns={[
              { key: "kind", header: "Kind", render: (r: any) => <Badge value="info">{r.kind}</Badge> },
              { key: "display_name", header: "Entity", render: (r: any) => <span className="text-ink-100">{r.display_name || r.value}</span> },
              { key: "criticality", header: "Criticality", render: (r: any) => <Badge kind="severity" value={r.criticality} /> },
              { key: "risk_score", header: "Risk", render: (r: any) => <span className="text-amber tabular-nums">{Math.round(r.risk_score)}</span> },
              { key: "is_internal", header: "Scope", render: (r: any) => (r.is_internal ? "internal" : "external") },
            ]}
          />
        )}
      </Panel>
    </div>
  );
}
