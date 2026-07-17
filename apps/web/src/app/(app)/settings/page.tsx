"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, Loading, Modal, PageHeader, Panel } from "@/components/ui";
import { titleCase } from "@/lib/ui";

export default function SettingsPage() {
  const { mode, refreshMode, can } = useApp();
  const [readiness, setReadiness] = useState<any>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [strategy, setStrategy] = useState(mode?.llm_strategy || "simulated");
  const [aiEnabled, setAiEnabled] = useState(mode?.ai_enabled ?? true);

  const manage = can("mode:manage");

  useEffect(() => {
    if (manage) api.get<any>("/mode/readiness").then(setReadiness).catch(() => {});
  }, [manage]);

  async function switchMode(target: "DEMO" | "LIVE", confirm = false) {
    try {
      await api.post("/mode/switch", { mode: target, confirm, ai_enabled: aiEnabled, llm_strategy: strategy });
      setToast(`Mode switched to ${target}.`);
      setConfirmOpen(false);
      refreshMode();
    } catch (e: any) {
      const d = e.detail || {};
      setToast(e.message || d.message || "Switch failed");
      setConfirmOpen(false);
    }
  }

  async function saveAiConfig() {
    try {
      await api.post("/mode/switch", { mode: mode?.mode, confirm: mode?.is_live ? true : undefined, ai_enabled: aiEnabled, llm_strategy: strategy });
      setToast("AI configuration saved.");
      refreshMode();
    } catch (e: any) { setToast(e.message); }
  }

  if (!mode) return <Loading />;

  return (
    <div>
      <PageHeader title="System Settings" subtitle="Operating mode, AI strategy and platform configuration" />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="Operating Mode" glow>
          <div className="flex items-center gap-3 mb-3">
            <Badge value={mode.is_live ? "critical" : "info"}>{mode.mode}</Badge>
            <span className="text-xs text-ink-400">changed {mode.changed_at ? new Date(mode.changed_at).toLocaleString() : "—"} by {mode.changed_by || "—"}</span>
          </div>
          <p className="text-sm text-ink-400 mb-4">
            {mode.is_live
              ? "LIVE: real connectors are used and approved response actions reach production systems through the governed gateway."
              : "DEMO: all data is synthetic, all actions are simulated and clearly labelled. No production-changing command can be sent."}
          </p>
          {!manage && <p className="text-xs text-amber">Switching modes requires the mode:manage permission (SOC Manager / admin).</p>}
          {manage && (
            <div className="space-y-3">
              {!mode.is_live ? (
                <>
                  <div className="rounded-lg border border-white/5 p-3">
                    <div className="label mb-2">Live readiness checks</div>
                    {readiness ? readiness.checks.map((c: any) => (
                      <div key={c.name} className="flex items-start gap-2 py-1 text-xs">
                        {c.passed ? <CheckCircle2 className="w-3.5 h-3.5 text-teal mt-0.5 shrink-0" /> : <XCircle className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${c.required ? "text-crit" : "text-amber"}`} />}
                        <div>
                          <span className="text-ink-200">{titleCase(c.name)}</span>{c.required && !c.passed && <span className="text-crit"> (required)</span>}
                          <div className="text-ink-500">{c.detail}</div>
                        </div>
                      </div>
                    )) : <Loading label="Checking…" />}
                  </div>
                  <button className="btn-danger w-full" disabled={!readiness?.ready} onClick={() => setConfirmOpen(true)}>
                    <ShieldAlert className="w-4 h-4" /> {readiness?.ready ? "Switch to LIVE mode…" : "LIVE blocked — readiness failed"}
                  </button>
                </>
              ) : (
                <button className="btn-primary w-full" onClick={() => switchMode("DEMO")}>Return to DEMO mode</button>
              )}
            </div>
          )}
        </Panel>

        <Panel title="AI Strategy">
          <div className="space-y-3">
            <label className="flex items-center gap-2 text-sm text-ink-200">
              <input type="checkbox" checked={aiEnabled} onChange={(e) => setAiEnabled(e.target.checked)} />
              AI assistance enabled
            </label>
            <div>
              <div className="label mb-1">LLM strategy</div>
              <select className="input" value={strategy} onChange={(e) => setStrategy(e.target.value)} disabled={!aiEnabled}>
                <option value="simulated">Simulated (deterministic, no external calls)</option>
                <option value="private">Private only (local vLLM/Ollama)</option>
                <option value="hosted">Hosted providers</option>
                <option value="hybrid">Hybrid routing (sensitivity-aware)</option>
                <option value="disabled">Disabled</option>
              </select>
              <p className="text-[11px] text-ink-500 mt-1">
                The platform remains fully usable with AI disabled or when every external provider is down — the deterministic pipeline and simulated reasoner keep workflows working.
              </p>
            </div>
            {manage && <button className="btn-primary" onClick={saveAiConfig}>Save AI configuration</button>}
          </div>
        </Panel>
      </div>

      <Modal open={confirmOpen} onClose={() => setConfirmOpen(false)} title="Confirm switch to LIVE mode">
        <div className="space-y-3 text-sm text-ink-300">
          <div className="flex items-start gap-2 text-amber"><AlertTriangle className="w-5 h-5 shrink-0" />
            <p>In LIVE mode, approved response actions are sent to real systems via configured connectors. Demo data remains separated. This action is audited.</p>
          </div>
          <button className="btn-danger w-full" onClick={() => switchMode("LIVE", true)}>I understand — activate LIVE mode</button>
        </div>
      </Modal>
    </div>
  );
}
