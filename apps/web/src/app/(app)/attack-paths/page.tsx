"use client";

import { useEffect, useState } from "react";
import { GitBranch, ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Loading, PageHeader, Panel } from "@/components/ui";

export default function AttackPathsPage() {
  const [data, setData] = useState<any>(null);
  useEffect(() => { api.get<any>("/entities/attack-paths").then(setData); }, []);

  return (
    <div>
      <PageHeader title="Attack-Path Explorer" subtitle="Chains from external/low-value nodes toward business-critical assets" />
      {!data ? <Loading /> : (
        <div className="space-y-3">
          {data.paths.map((p: any, i: number) => (
            <Panel key={i} title={<span className="flex items-center gap-2"><GitBranch className="w-4 h-4 text-amber" /> Path {i + 1}</span>}
              actions={<Badge kind="severity" value={p.risk > 70 ? "critical" : p.risk > 40 ? "high" : "medium"}>risk {Math.round(p.risk)}</Badge>}>
              <div className="flex flex-wrap items-center gap-2">
                {p.nodes.map((n: any, j: number) => (
                  <div key={j} className="flex items-center gap-2">
                    <span className={`chip ${n.criticality === "critical" || n.criticality === "high" ? "text-crit border-crit/40 bg-crit/10 shadow-glow-crit" : "text-ink-200 border-white/10 bg-white/5"}`}>{n.label}</span>
                    {j < p.nodes.length - 1 && <ArrowRight className="w-4 h-4 text-ink-500" />}
                  </div>
                ))}
              </div>
            </Panel>
          ))}
          {!data.paths.length && <div className="text-ink-500 text-sm py-10 text-center">No attack paths reaching critical assets in the current graph.</div>}
        </div>
      )}
    </div>
  );
}
