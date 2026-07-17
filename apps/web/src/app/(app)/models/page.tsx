"use client";

import { useEffect, useState } from "react";
import { Cpu, Plus, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, Loading, Modal, PageHeader, Panel } from "@/components/ui";
import { titleCase } from "@/lib/ui";

const PROVIDER_KINDS = ["openai", "azure_openai", "anthropic", "gemini", "bedrock", "vllm", "ollama", "openai_compatible"];

export default function ModelsPage() {
  const { can } = useApp();
  const [providers, setProviders] = useState<any[]>([]);
  const [routes, setRoutes] = useState<any[]>([]);
  const [usage, setUsage] = useState<any>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, any>>({});
  const [addOpen, setAddOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  async function load() {
    const [p, r, u] = await Promise.all([
      api.get<any>("/models/providers"), api.get<any>("/models/routes"), api.get<any>("/models/usage"),
    ]);
    setProviders(p.items); setRoutes(r.items); setUsage(u);
  }
  useEffect(() => { load(); }, []);

  async function test(id: string) {
    setTesting(id);
    try {
      const res = await api.post<any>(`/models/providers/${id}/test`);
      setResults((prev) => ({ ...prev, [id]: res }));
      load();
    } catch (e: any) { setResults((prev) => ({ ...prev, [id]: { state: "unhealthy", detail: e.message } })); }
    finally { setTesting(null); }
  }

  if (!usage) return <Loading />;

  return (
    <div>
      <PageHeader
        title="AI Model Operations"
        subtitle="Multi-LLM gateway · capability routing · real connectivity tests"
        actions={can("model:manage") && <button className="btn-primary" onClick={() => setAddOpen(true)}><Plus className="w-4 h-4" /> Add provider</button>}
      />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 space-y-3">
          {providers.map((p) => (
            <Panel key={p.id} title={<span className="flex items-center gap-2"><Cpu className="w-4 h-4 text-violet" /> {p.name}</span>}
              actions={<div className="flex items-center gap-2">
                <Badge value={p.health}>{titleCase(p.health)}</Badge>
                {can("model:read") && <button className="btn-ghost !py-1 !text-xs" onClick={() => test(p.id)} disabled={testing === p.id}>{testing === p.id ? "Testing…" : "Test"}</button>}
              </div>}>
              <div className="flex flex-wrap gap-2 text-xs text-ink-400">
                <span className="chip border-white/10">{p.kind}</span>
                {p.private_only && <span className="chip text-teal border-teal/30">private-only</span>}
                <span className="chip border-white/10">secret: {p.secret_configured ? "configured" : "none"}</span>
                <span className="chip border-white/10">{p.deployments?.length || 0} deployments</span>
              </div>
              {results[p.id] && (
                <div className={`text-xs mt-2 ${results[p.id].state === "healthy" ? "text-teal" : results[p.id].state === "not_configured" ? "text-ink-400" : "text-crit"}`}>
                  {results[p.id].detail} {results[p.id].latency_ms ? `(${results[p.id].latency_ms}ms)` : ""}
                </div>
              )}
              <div className="flex flex-wrap gap-1 mt-2">
                {p.deployments?.map((d: any) => (
                  <span key={d.id} className="chip text-ink-300 border-white/10" title={d.capabilities?.join(", ")}>{d.model_identifier}</span>
                ))}
              </div>
            </Panel>
          ))}
        </div>

        <div className="space-y-4">
          <Panel title="Capability Routing">
            <div className="space-y-1.5 text-sm">
              {routes.map((r) => (
                <div key={r.id} className="flex items-center justify-between py-1 border-b border-white/5 last:border-0">
                  <span className="text-ink-300">{r.capability}</span>
                  {r.require_verification && <Badge value="info">verified</Badge>}
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="Usage & Cost">
            {usage.providers.map((p: any) => (
              <div key={p.name} className="flex items-center justify-between text-sm py-1 border-b border-white/5 last:border-0">
                <span className="text-ink-300">{p.name}</span>
                <span className="text-xs text-ink-500">{p.total_tokens} tok · ${p.total_cost_usd}</span>
              </div>
            ))}
          </Panel>
        </div>
      </div>

      <AddProviderModal open={addOpen} onClose={() => setAddOpen(false)} onSaved={() => { setAddOpen(false); load(); setToast("Provider added. Configure a secret ref then Test connectivity."); }} />
    </div>
  );
}

function AddProviderModal({ open, onClose, onSaved }: any) {
  const [form, setForm] = useState<any>({ kind: "openai", name: "", base_url: "", secret_ref: "" });
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    try {
      await api.post("/models/providers", { ...form, deployments: form.model ? [{ model_identifier: form.model, capabilities: ["deep_investigator"] }] : [] });
      onSaved();
    } catch (e: any) { setErr(e.message); }
  }
  return (
    <Modal open={open} onClose={onClose} title="Add Model Provider">
      <div className="space-y-3">
        <div>
          <label className="label block mb-1">Kind</label>
          <select className="input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {PROVIDER_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </div>
        <div><label className="label block mb-1">Name</label><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        <div><label className="label block mb-1">Base URL (optional)</label><input className="input" placeholder="https://api.openai.com" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /></div>
        <div><label className="label block mb-1">Model identifier</label><input className="input" placeholder="gpt-4o" value={form.model || ""} onChange={(e) => setForm({ ...form, model: e.target.value })} /></div>
        <div>
          <label className="label block mb-1">Secret reference (never a plaintext key)</label>
          <input className="input" placeholder="vault://openai#api_key or env://OPENAI_KEY" value={form.secret_ref} onChange={(e) => setForm({ ...form, secret_ref: e.target.value })} />
          <p className="text-[11px] text-ink-500 mt-1">Keys are resolved from the secret manager; they are never stored in the DB or browser.</p>
        </div>
        {err && <div className="text-sm text-crit">{err}</div>}
        <button className="btn-primary w-full" onClick={save}>Save provider</button>
      </div>
    </Modal>
  );
}
