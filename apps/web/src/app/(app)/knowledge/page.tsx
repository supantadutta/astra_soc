"use client";

import { useEffect, useState } from "react";
import { BrainCircuit, Search, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, Loading, Modal, PageHeader, Panel } from "@/components/ui";
import { titleCase } from "@/lib/ui";

export default function KnowledgePage() {
  const { can } = useApp();
  const [docs, setDocs] = useState<any>(null);
  const [scope, setScope] = useState("");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<any[] | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  async function load() { setDocs(await api.get<any>(`/knowledge/documents${scope ? `?scope=${scope}` : ""}`)); }
  useEffect(() => { load(); }, [scope]);

  async function search() {
    if (!q) { setResults(null); return; }
    const r = await api.post<any>("/knowledge/search", { query: q });
    setResults(r.results);
  }

  return (
    <div>
      <PageHeader title="Knowledge & Memory" subtitle="Tenant-scoped retrieval · secrets scrubbed at ingest · RBAC-filtered"
        actions={can("knowledge:write") && <button className="btn-primary" onClick={() => setAddOpen(true)}><Plus className="w-4 h-4" /> Add document</button>} />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}

      <Panel className="mb-4">
        <div className="flex gap-2">
          <input className="input" placeholder="Semantic search across memory scopes…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
          <button className="btn-primary" onClick={search}><Search className="w-4 h-4" /> Search</button>
        </div>
        {results && (
          <div className="mt-3 space-y-2">
            {results.map((r: any) => (
              <div key={r.chunk_id} className="rounded-lg border border-white/5 p-3">
                <div className="flex items-center justify-between text-xs mb-1"><Badge value="info">{r.scope}</Badge><span className="text-ink-500">score {r.score}</span></div>
                <div className="text-sm text-ink-300">{r.content}</div>
              </div>
            ))}
            {!results.length && <div className="text-ink-500 text-sm py-4 text-center">No matches.</div>}
          </div>
        )}
      </Panel>

      <Panel title="Documents">
        <div className="flex gap-2 mb-3 flex-wrap">
          {["", "tenant_knowledge", "global_knowledge", "playbook_knowledge", "detection_knowledge", "threat_intel_knowledge"].map((s) => (
            <button key={s} onClick={() => setScope(s)} className={`btn-ghost !text-xs ${scope === s ? "!text-cyan !border-cyan/40" : ""}`}>{s ? titleCase(s) : "All"}</button>
          ))}
        </div>
        {!docs ? <Loading /> : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {docs.items.map((d: any) => (
              <div key={d.id} className="rounded-lg border border-white/5 p-3">
                <div className="flex items-center justify-between"><span className="flex items-center gap-2 text-sm text-ink-100"><BrainCircuit className="w-4 h-4 text-violet" /> {d.title}</span><Badge value="info">{d.scope}</Badge></div>
                <div className="text-xs text-ink-500 mt-1">{d.classification} · trust {d.trust_score} · {d.source || "—"}</div>
              </div>
            ))}
            {!docs.items.length && <div className="text-ink-500 text-sm py-6 text-center col-span-2">No documents in this scope.</div>}
          </div>
        )}
      </Panel>

      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Add Knowledge Document">
        <AddDoc onSaved={() => { setAddOpen(false); load(); setToast("Document ingested (secrets scrubbed)."); }} />
      </Modal>
    </div>
  );
}

function AddDoc({ onSaved }: any) {
  const [form, setForm] = useState<any>({ title: "", body: "", scope: "tenant_knowledge", classification: "internal" });
  async function save() { await api.post("/knowledge/documents", form); onSaved(); }
  return (
    <div className="space-y-3">
      <input className="input" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
      <textarea className="input h-32" placeholder="Body…" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
      <select className="input" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
        {["tenant_knowledge", "global_knowledge", "playbook_knowledge", "detection_knowledge", "threat_intel_knowledge"].map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <button className="btn-primary w-full" onClick={save}>Ingest</button>
    </div>
  );
}
