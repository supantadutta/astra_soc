"use client";

import { useState } from "react";
import { CheckCheck, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useApp } from "@/lib/store";
import { EmptyState, ErrorState, Modal, PageHeader, Panel, Skeleton } from "@/components/ui";
import { Field, ResultBanner, SlaBadge, useAction, useOpenInTenant } from "@/components/mssp";
import { fmtDate, timeAgo } from "@/lib/ui";

interface Handover {
  id: string; shift: string; summary: string; author_id: string; author_label: string; created_at: string;
  acknowledged_by: string | null; acknowledged_at: string | null;
  open_items: { tenant_id: string | null; incident_id: string | null; incident_key: string | null; note: string; owner?: string }[];
}

export default function HandoverPage() {
  const { me } = useApp();
  const openIn = useOpenInTenant();
  const list = useApi<{ items: Handover[] }>("/mssp/handovers?limit=30");
  const action = useAction();
  const [creating, setCreating] = useState(false);

  const ack = async (h: Handover) => {
    await action.run(() => api.post(`/mssp/handovers/${h.id}/acknowledge`), "Handover acknowledged — you now own the open items.");
    list.reload();
  };

  return (
    <div>
      <PageHeader
        title="Shift Handover"
        subtitle="Structured, auditable handover between SOC shifts. The incoming shift acknowledges; authors cannot acknowledge their own handover."
        actions={<button className="btn-primary" onClick={() => setCreating(true)}><Plus className="w-4 h-4" /> New handover</button>}
      />
      <ResultBanner result={action.result} />
      {list.error ? <ErrorState message={list.error.message} /> : list.loading && !list.data ? <Skeleton rows={4} /> : (
        <div className="space-y-3">
          {!list.data?.items.length && <Panel><EmptyState label="No handovers yet." /></Panel>}
          {list.data?.items.map((h) => (
            <Panel key={h.id}
              title={<div><span className="card-title">{h.shift || "Shift"} handover</span><span className="text-xs text-ink-500 ml-2">{h.author_label} · {timeAgo(h.created_at)}</span></div>}
              actions={h.acknowledged_at
                ? <span className="text-xs text-teal">Acknowledged {fmtDate(h.acknowledged_at)}</span>
                : h.author_id === me?.id
                  ? <span className="text-xs text-amber">Awaiting incoming shift</span>
                  : <button className="btn-primary !py-1 !text-xs" onClick={() => ack(h)}><CheckCheck className="w-3.5 h-3.5" /> Acknowledge</button>}
            >
              <p className="text-sm text-ink-200 whitespace-pre-wrap">{h.summary || <i className="text-ink-500">No summary.</i>}</p>
              {h.open_items.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  <div className="label">Open items</div>
                  {h.open_items.map((it, i) => (
                    <div key={i} className="flex items-start gap-2 text-sm border border-white/5 rounded-lg px-3 py-2">
                      {it.incident_id && it.tenant_id ? (
                        <button className="font-mono text-xs text-cyan hover:underline shrink-0" onClick={() => openIn(it.tenant_id!, `/incidents/${it.incident_id}`)}>{it.incident_key}</button>
                      ) : <span className="text-xs text-ink-500 shrink-0">note</span>}
                      <span className="text-ink-300">{it.note}</span>
                      {it.owner && <span className="ml-auto text-xs text-ink-500">→ {it.owner}</span>}
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          ))}
        </div>
      )}
      {creating && <NewHandover onClose={() => setCreating(false)} onDone={() => { setCreating(false); list.reload(); }} />}
    </div>
  );
}

function NewHandover({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const queue = useApi<{ items: { id: string; key: string; title: string; severity: string; tenant: { name: string }; sla: { overall: string } }[] }>("/mssp/queue?page_size=100");
  const action = useAction();
  const hour = new Date().getHours();
  const [shift, setShift] = useState(hour < 8 ? "Night" : hour < 16 ? "Day" : "Evening");
  const [summary, setSummary] = useState("");
  const [items, setItems] = useState<{ incident_id: string; note: string; owner: string }[]>([]);

  const submit = async () => {
    const ok = await action.run(() => api.post("/mssp/handovers", {
      shift, summary, open_items: items.map((i) => ({ incident_id: i.incident_id || undefined, note: i.note, owner: i.owner || undefined })),
    }), "Handover published.");
    if (ok) onDone();
  };

  return (
    <Modal open onClose={onClose} title="New shift handover" wide>
      <ResultBanner result={action.result} />
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-3">
        <Field label="Shift">
          <select className="input" value={shift} onChange={(e) => setShift(e.target.value)}>
            {["Day", "Evening", "Night", "Weekend"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </Field>
        <div className="md:col-span-3">
          <Field label="Summary"><textarea className="input min-h-24" value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="What happened, what is in flight, what to watch." /></Field>
        </div>
      </div>
      <div className="label mb-2">Open items</div>
      <div className="space-y-2 mb-3">
        {items.map((it, i) => (
          <div key={i} className="grid grid-cols-12 gap-2 items-start">
            <select className="input col-span-4 !text-xs" value={it.incident_id} onChange={(e) => setItems(items.map((x, j) => j === i ? { ...x, incident_id: e.target.value } : x))}>
              <option value="">(general note)</option>
              {queue.data?.items.map((q) => <option key={q.id} value={q.id}>{q.key} · {q.tenant.name} · {q.severity}</option>)}
            </select>
            <input className="input col-span-5 !text-xs" placeholder="Status / next step" value={it.note} onChange={(e) => setItems(items.map((x, j) => j === i ? { ...x, note: e.target.value } : x))} />
            <input className="input col-span-2 !text-xs" placeholder="Owner" value={it.owner} onChange={(e) => setItems(items.map((x, j) => j === i ? { ...x, owner: e.target.value } : x))} />
            <button className="btn-ghost !px-2 col-span-1" onClick={() => setItems(items.filter((_, j) => j !== i))} aria-label="Remove item"><Trash2 className="w-3.5 h-3.5" /></button>
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost !text-xs" onClick={() => setItems([...items, { incident_id: "", note: "", owner: "" }])}><Plus className="w-3.5 h-3.5" /> Add item</button>
          <button className="btn-ghost !text-xs" disabled={!queue.data} onClick={() => setItems([...items, ...(queue.data?.items || [])
            .filter((q) => ["breached", "at_risk"].includes(q.sla.overall) && !items.some((x) => x.incident_id === q.id))
            .map((q) => ({ incident_id: q.id, note: `${q.title} — SLA ${q.sla.overall.replace("_", " ")}`, owner: "" }))])}>
            Add all SLA breaches / at-risk
          </button>
        </div>
        {queue.data && <div className="text-[11px] text-ink-500 flex items-center gap-2">Queue now: {queue.data.items.length} open ·
          <SlaBadge state="breached" /> {queue.data.items.filter((q) => q.sla.overall === "breached").length}
          <SlaBadge state="at_risk" /> {queue.data.items.filter((q) => q.sla.overall === "at_risk").length}</div>}
      </div>
      <div className="flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" onClick={submit} disabled={action.busy || (!summary && !items.length)}>{action.busy ? "Publishing…" : "Publish handover"}</button>
      </div>
    </Modal>
  );
}
