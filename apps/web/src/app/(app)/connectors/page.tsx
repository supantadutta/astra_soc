"use client";

import { useEffect, useState } from "react";
import { Boxes, Settings2 } from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, Loading, Modal, PageHeader, Panel } from "@/components/ui";
import { titleCase } from "@/lib/ui";

const CATS = ["", "siem", "edr", "ndr", "identity", "threat_intel", "itsm", "comms", "cloud"];

export default function ConnectorsPage() {
  const { can } = useApp();
  const [items, setItems] = useState<any[]>([]);
  const [cat, setCat] = useState("");
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, any>>({});
  const [edit, setEdit] = useState<any>(null);
  const [toast, setToast] = useState<string | null>(null);

  async function load() {
    const r = await api.get<any>(`/connectors${cat ? `?category=${cat}` : ""}`);
    setItems(r.items);
  }
  useEffect(() => { load(); }, [cat]);

  async function test(id: string) {
    setTesting(id);
    try {
      const res = await api.post<any>(`/connectors/${id}/test`);
      setResults((p) => ({ ...p, [id]: res }));
      load();
    } catch (e: any) { setResults((p) => ({ ...p, [id]: { state: "unhealthy", detail: e.message } })); }
    finally { setTesting(null); }
  }

  if (!items) return <Loading />;

  return (
    <div>
      <PageHeader title="Integrations" subtitle="Connector framework · real adapters + mock servers · read/write separation" />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}
      <div className="flex flex-wrap gap-2 mb-4">
        {CATS.map((c) => <button key={c} onClick={() => setCat(c)} className={`btn-ghost !text-xs ${cat === c ? "!text-cyan !border-cyan/40" : ""}`}>{c ? titleCase(c) : "All"}</button>)}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {items.map((c) => (
          <Panel key={c.id} title={<span className="flex items-center gap-2"><Boxes className="w-4 h-4 text-cyan" /> {c.name}</span>}
            actions={<Badge value={c.enabled ? "healthy" : "not_configured"}>{c.enabled ? "on" : "off"}</Badge>}>
            <div className="flex flex-wrap gap-1.5 text-[10px] text-ink-400 mb-2">
              <span className="chip border-white/10">{c.category}</span>
              {c.use_mock && <span className="chip text-amber border-amber/30">mock</span>}
              {c.can_write && <span className="chip text-crit border-crit/30">write-capable</span>}
              {c.latest_health && <Badge value={c.latest_health.state}>{titleCase(c.latest_health.state)}</Badge>}
            </div>
            {results[c.id] && (
              <div className={`text-xs mb-2 ${results[c.id].state === "healthy" ? "text-teal" : results[c.id].state === "not_configured" ? "text-ink-400" : "text-crit"}`}>
                {results[c.id].detail} {results[c.id].mock ? "(mock)" : ""}
              </div>
            )}
            <div className="flex gap-2">
              {can("connector:manage") && <button className="btn-ghost !py-1 !text-xs" onClick={() => test(c.id)} disabled={testing === c.id}>{testing === c.id ? "Testing…" : "Test connection"}</button>}
              {can("connector:manage") && <button className="btn-ghost !py-1 !text-xs" onClick={() => setEdit(c)}><Settings2 className="w-3.5 h-3.5" /> Configure</button>}
            </div>
          </Panel>
        ))}
      </div>

      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.name || "Connector"}>
        {edit && <ConnectorForm connector={edit} onSaved={() => { setEdit(null); load(); setToast("Connector updated."); }} />}
      </Modal>
    </div>
  );
}

function ConnectorForm({ connector, onSaved }: any) {
  const [form, setForm] = useState<any>({
    enabled: connector.enabled, use_mock: connector.use_mock, base_url: connector.base_url || "",
    can_write: connector.can_write, secret_ref: connector.credential_refs?.[0]?.secret_ref || "",
  });
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    try {
      await api.patch(`/connectors/${connector.id}`, {
        enabled: form.enabled, use_mock: form.use_mock, base_url: form.base_url, can_write: form.can_write,
        credential_refs: form.secret_ref ? [{ field: "api_token", secret_ref: form.secret_ref }] : undefined,
      });
      onSaved();
    } catch (e: any) { setErr(e.message); }
  }
  return (
    <div className="space-y-3 text-sm">
      <label className="flex items-center gap-2"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> Enabled</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={form.use_mock} onChange={(e) => setForm({ ...form, use_mock: e.target.checked })} /> Use built-in mock server</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={form.can_write} onChange={(e) => setForm({ ...form, can_write: e.target.checked })} /> Allow write (response) actions</label>
      <div><label className="label block mb-1">Base URL</label><input className="input" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://vendor.example.com" /></div>
      <div>
        <label className="label block mb-1">Secret reference</label>
        <input className="input" value={form.secret_ref} onChange={(e) => setForm({ ...form, secret_ref: e.target.value })} placeholder="vault://splunk#token" />
        <p className="text-[11px] text-ink-500 mt-1">Uncheck “mock” and supply base URL + secret to test a real connection.</p>
      </div>
      {err && <div className="text-crit">{err}</div>}
      <button className="btn-primary w-full" onClick={save}>Save</button>
    </div>
  );
}
