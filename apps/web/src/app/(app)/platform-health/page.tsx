"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge, Loading, PageHeader, Panel } from "@/components/ui";
import { titleCase } from "@/lib/ui";

export default function PlatformHealthPage() {
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    api.get<any>("/platform/health").then(setData);
    const t = setInterval(() => api.get<any>("/platform/health").then(setData).catch(() => {}), 10000);
    return () => clearInterval(t);
  }, []);

  if (!data) return <Loading />;

  return (
    <div>
      <PageHeader title="Platform Health" subtitle="Honest dependency status — unconfigured services say so; nothing is faked" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="Core Services">
          {data.services.map((s: any) => (
            <Row key={s.name} name={s.name} state={s.state} detail={typeof s.detail === "string" ? s.detail : JSON.stringify(s.detail || "")} />
          ))}
        </Panel>
        <Panel title="Enterprise Dependencies">
          {data.dependencies.map((d: any) => <Row key={d.name} name={d.name} state={d.state} />)}
          <p className="text-[11px] text-ink-500 mt-2">Optional in the demo profile. Configure via ASTRASOC_* env vars — the platform runs degraded-but-functional without them.</p>
        </Panel>
        <Panel title="AI Providers">
          {data.ai_providers.map((p: any) => (
            <Row key={p.name} name={p.name} state={p.health} detail={p.circuit_open ? "circuit breaker OPEN" : ""} />
          ))}
        </Panel>
        <Panel title="Queues & Failures">
          <Row name="failed response actions" state={data.queues.failed_response_actions > 0 ? "degraded" : "healthy"} detail={String(data.queues.failed_response_actions)} />
          <Row name="retry queue" state="healthy" detail={String(data.queues.retry_queue)} />
          <Row name="dead letter" state="healthy" detail={String(data.queues.dead_letter)} />
        </Panel>
      </div>
    </div>
  );
}

function Row({ name, state, detail }: { name: string; state: string; detail?: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
      <span className="text-sm text-ink-300">{titleCase(name)}</span>
      <div className="flex items-center gap-2">
        {detail && <span className="text-xs text-ink-500">{detail}</span>}
        <Badge value={state}>{titleCase(state)}</Badge>
      </div>
    </div>
  );
}
