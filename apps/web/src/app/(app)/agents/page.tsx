"use client";

import { useEffect, useState } from "react";
import { Bot, Cpu, Timer, Coins } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Loading, Panel, PageHeader, SimBadge } from "@/components/ui";
import { titleCase, timeAgo } from "@/lib/ui";

export default function AgentsPage() {
  const [agents, setAgents] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);

  useEffect(() => {
    api.get<any>("/agents").then((r) => setAgents(r.items));
    api.get<any>("/agents/runs?page_size=20").then((r) => setRuns(r.items));
  }, []);

  return (
    <div>
      <PageHeader title="Agent Command Center" subtitle={`${agents.length} bounded specialist agents`} />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Panel title="Registered Agents">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[560px] overflow-y-auto pr-1">
            {agents.map((a) => (
              <div key={a.id} className="rounded-lg border border-white/5 p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="flex items-center gap-2 text-sm text-ink-100"><Bot className="w-4 h-4 text-violet" /> {a.name}</span>
                  <Badge value={a.enabled ? "healthy" : "not_configured"}>{a.enabled ? "enabled" : "disabled"}</Badge>
                </div>
                <p className="text-xs text-ink-400">{a.purpose}</p>
                <div className="flex flex-wrap gap-2 mt-2 text-[10px] text-ink-500">
                  <span className="flex items-center gap-1"><Cpu className="w-3 h-3" />{a.required_capability}</span>
                  <span className="flex items-center gap-1"><Timer className="w-3 h-3" />{a.max_execution_seconds}s</span>
                  <span className="flex items-center gap-1"><Coins className="w-3 h-3" />{(a.max_token_budget / 1000)}k tok</span>
                  <span>{a.tool_allowlist?.length || 0} tools</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Recent Agent Runs">
          <div className="space-y-2 max-h-[560px] overflow-y-auto pr-1">
            {runs.map((r) => (
              <div key={r.id} className="rounded-lg border border-white/5 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-ink-100">{titleCase(r.agent_key)}</span>
                  <div className="flex items-center gap-2">
                    {r.simulated && <SimBadge />}
                    <Badge kind="status" value={r.status} />
                  </div>
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs text-ink-500">
                  <span>{r.provider_used || "—"}</span>
                  <span>{r.tokens_used} tok</span>
                  <span>{r.tool_calls_made} tools</span>
                  <span>{timeAgo(r.created_at)}</span>
                </div>
                {r.output?.claim && <div className="text-xs text-ink-400 mt-1 truncate">{r.output.claim.claim}</div>}
              </div>
            ))}
            {!runs.length && <div className="text-ink-500 text-sm py-8 text-center">No agent runs yet. Open an incident and run an investigation.</div>}
          </div>
        </Panel>
      </div>
    </div>
  );
}
