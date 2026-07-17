"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  Bot, CheckCircle2, FileText, Network, Play, ShieldQuestion, Sparkles, Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, ConfidenceBar, Loading, Modal, Panel, SimBadge } from "@/components/ui";
import { EntityGraph } from "@/components/EntityGraph";
import { EVIDENCE_KIND_META, cx, fmtDate, timeAgo, titleCase } from "@/lib/ui";

const TABS = ["Timeline", "Evidence & Hypotheses", "Entity Graph", "Agents", "Response", "Reports"] as const;

export default function IncidentWorkspace() {
  const { id } = useParams<{ id: string }>();
  const { can, mode } = useApp();
  const [data, setData] = useState<any>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Timeline");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(async () => {
    setData(await api.get<any>(`/incidents/${id}`));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  if (!data) return <Loading label="Loading investigation workspace…" />;
  const inc = data.incident;

  async function investigate() {
    setBusy(true);
    try {
      await api.post(`/incidents/${id}/investigate`);
      setToast("Coordinator workflow executed — agents produced new hypotheses & evidence.");
      await load();
    } catch (e: any) { setToast(e.message); } finally { setBusy(false); }
  }

  return (
    <div>
      {toast && (
        <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2 flex justify-between">
          {toast}<button onClick={() => setToast(null)} className="text-ink-400">✕</button>
        </div>
      )}

      {/* Header */}
      <div className="panel p-4 mb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono text-cyan text-sm">{inc.key}</span>
              <Badge kind="severity" value={inc.severity} />
              <Badge kind="status" value={inc.status} />
              {inc.data_scope === "DEMO" && <SimBadge />}
            </div>
            <h1 className="text-xl font-bold text-ink-100">{inc.title}</h1>
            <p className="text-sm text-ink-400 mt-1 max-w-3xl">{inc.summary}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {can("agent:run") && (
              <button className="btn-violet" onClick={investigate} disabled={busy}>
                <Sparkles className="w-4 h-4" /> {busy ? "Investigating…" : "Run Investigation"}
              </button>
            )}
          </div>
        </div>

        {/* Meta strip */}
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3 mt-4">
          <Meta label="Confidence"><ConfidenceBar value={inc.confidence} /></Meta>
          <Meta label="Business Risk"><span className="text-amber font-bold">{Math.round(inc.business_risk)}/100</span></Meta>
          <Meta label="Affected Hosts">{inc.affected_hosts?.length || 0}</Meta>
          <Meta label="Affected Users">{inc.affected_users?.length || 0}</Meta>
          <Meta label="Created">{timeAgo(inc.created_at)}</Meta>
          <Meta label="Updated">{timeAgo(inc.updated_at)}</Meta>
        </div>

        {/* ATT&CK */}
        {inc.attack_techniques?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {inc.attack_tactics?.map((t: string) => <span key={t} className="chip text-violet border-violet/30 bg-violet/10">{t}</span>)}
            {inc.attack_techniques?.map((t: string) => <span key={t} className="chip text-ink-300 border-white/10 bg-white/5 font-mono">{t}</span>)}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-white/5 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cx(
              "px-4 py-2 text-sm border-b-2 -mb-px whitespace-nowrap transition-colors",
              tab === t ? "border-cyan text-cyan" : "border-transparent text-ink-400 hover:text-ink-200"
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Timeline" && <TimelineTab data={data} />}
      {tab === "Evidence & Hypotheses" && <EvidenceTab data={data} reload={load} canPromote={can("evidence:write")} setToast={setToast} />}
      {tab === "Entity Graph" && (
        <Panel title="Entity & Attack Graph">
          <EntityGraph nodes={data.entities.map((e: any) => ({ id: e.id, label: e.display_name || e.value, kind: e.kind, criticality: e.criticality }))} edges={data.relationships} />
        </Panel>
      )}
      {tab === "Agents" && <AgentsTab data={data} />}
      {tab === "Response" && <ResponseTab data={data} incidentId={id} reload={load} setToast={setToast} />}
      {tab === "Reports" && <ReportsTab incidentId={id} setToast={setToast} />}
    </div>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className="text-sm text-ink-100 mt-0.5">{children}</div>
    </div>
  );
}

function TimelineTab({ data }: { data: any }) {
  return (
    <Panel title="Incident Timeline">
      <div className="relative pl-6">
        <div className="absolute left-2 top-1 bottom-1 w-px bg-white/10" />
        {data.timeline.map((t: any) => (
          <div key={t.id} className="relative mb-4">
            <span className={cx("absolute -left-[19px] top-1 w-3 h-3 rounded-full border-2 border-navy-800",
              t.category === "action" ? "bg-amber" : t.category === "note" ? "bg-cyan" : "bg-teal")} />
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-ink-100 font-medium">{t.title}</span>
              <Badge value="info">{titleCase(t.category)}</Badge>
              {t.attack_techniques?.map((x: string) => <span key={x} className="chip text-ink-400 border-white/10 font-mono text-[10px]">{x}</span>)}
            </div>
            {t.detail && <p className="text-sm text-ink-400 mt-0.5">{t.detail}</p>}
            <div className="text-xs text-ink-500 mt-0.5">{fmtDate(t.occurred_at)} {t.actor && `· ${t.actor}`}</div>
          </div>
        ))}
        {!data.timeline.length && <div className="text-ink-500 text-sm py-6">No timeline entries.</div>}
      </div>
    </Panel>
  );
}

function EvidenceTab({ data, reload, canPromote, setToast }: any) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Panel title="Evidence" actions={<span className="text-[11px] text-ink-500">Facts vs inferences kept distinct</span>}>
        <div className="space-y-2 max-h-[520px] overflow-y-auto pr-1">
          {data.evidence.map((e: any) => {
            const meta = EVIDENCE_KIND_META[e.kind] || { label: e.kind, color: "", note: "" };
            return (
              <div key={e.id} className="rounded-lg border border-white/5 p-3">
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className={cx("chip", meta.color)}>{meta.label}</span>
                  <span className="text-xs text-ink-500">{e.source}</span>
                </div>
                <div className="text-sm text-ink-100">{e.title}</div>
                <div className="text-xs text-ink-400 mt-1">{e.content}</div>
                <div className="text-[10px] text-ink-500 mt-1 font-mono">evidence:{e.id.slice(0, 8)} · conf {Math.round(e.confidence * 100)}%</div>
              </div>
            );
          })}
        </div>
      </Panel>

      <Panel title="Hypotheses & Missing Evidence">
        <div className="space-y-3 max-h-[520px] overflow-y-auto pr-1">
          {data.hypotheses.map((h: any) => (
            <div key={h.id} className={cx("rounded-lg border p-3", h.is_primary ? "border-violet/40 bg-violet/5" : "border-white/5")}>
              <div className="flex items-center justify-between gap-2 mb-1">
                <div className="flex items-center gap-2">
                  {h.is_primary && <Badge value="investigating">Primary</Badge>}
                  <span className="chip text-violet border-violet/30 bg-violet/10">{h.produced_by}</span>
                </div>
                <ConfidenceBar value={h.confidence} />
              </div>
              <div className="text-sm text-ink-100">{h.statement}</div>
              {h.missing_evidence?.length > 0 && (
                <div className="mt-2">
                  <div className="label mb-1">Missing evidence</div>
                  {h.missing_evidence.map((m: string, i: number) => (
                    <div key={i} className="text-xs text-amber flex items-center gap-1.5"><ShieldQuestion className="w-3 h-3" /> {m}</div>
                  ))}
                </div>
              )}
              <div className="text-[10px] text-ink-500 mt-2">
                Supports: {h.supporting_evidence_ids?.length || 0} evidence item(s)
              </div>
              {canPromote && !h.is_primary && (
                <button
                  className="btn-ghost mt-2 !py-1 !text-xs"
                  onClick={async () => {
                    try { await api.post(`/incidents/${data.incident.id}/promote-hypothesis/${h.id}`); setToast("Hypothesis promoted to an analyst conclusion."); reload(); }
                    catch (e: any) { setToast(e.message); }
                  }}
                >
                  <CheckCircle2 className="w-3.5 h-3.5" /> Promote to analyst conclusion
                </button>
              )}
            </div>
          ))}
          {!data.hypotheses.length && <div className="text-ink-500 text-sm py-6">No hypotheses yet. Run an investigation.</div>}
        </div>
      </Panel>
    </div>
  );
}

function AgentsTab({ data }: { data: any }) {
  return (
    <Panel title="Agent Activity" actions={<Badge value="info">evidence-first output</Badge>}>
      <div className="space-y-2">
        {data.agent_runs.map((r: any) => (
          <div key={r.id} className="rounded-lg border border-white/5 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-sm text-ink-100"><Bot className="w-4 h-4 text-violet" /> {titleCase(r.agent_key)}</span>
              <div className="flex items-center gap-2">
                {r.simulated && <SimBadge />}
                <Badge kind="status" value={r.status} />
              </div>
            </div>
            {r.output?.claim && (
              <div className="mt-2 text-sm text-ink-300">
                <span className="text-violet">Claim:</span> {r.output.claim.claim}
                <div className="flex items-center gap-3 mt-1 text-xs text-ink-500">
                  <span>conf {Math.round((r.output.claim.confidence || 0) * 100)}%</span>
                  <span>{r.output.claim.evidence_ids?.length || 0} evidence cited</span>
                  <span>{r.provider_used} · {r.model_used}</span>
                </div>
                {r.output.verification && (
                  <div className="text-xs mt-1 text-teal">
                    ✓ Verified via {r.output.verification.method} — agreement: {String(r.output.verification.agreement)}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {!data.agent_runs.length && <div className="text-ink-500 text-sm py-6">No agent runs yet. Click “Run Investigation”.</div>}
      </div>
    </Panel>
  );
}

function ResponseTab({ data, incidentId, reload, setToast }: any) {
  const { can } = useApp();
  const [recs, setRecs] = useState<any[]>([]);
  const [modal, setModal] = useState<any>(null);

  useEffect(() => {
    api.get<any>(`/incidents/${incidentId}/recommended-actions`).then((r) => setRecs(r.recommendations)).catch(() => {});
  }, [incidentId]);

  async function createAction(rec: any) {
    try {
      const res = await api.post<any>(`/response/actions`, {
        action_type: rec.action, target: rec.target, incident_id: incidentId,
        evidence_ids: rec.suggested_evidence_ids, confidence: rec.confidence,
        expected_outcome: rec.rationale,
      });
      setToast(`Action created — policy: ${res.policy_decision?.effect}. Status: ${res.action.status}.`);
      reload();
    } catch (e: any) { setToast(e.message || "Could not create action"); }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Panel title="Recommended Actions" actions={<Badge value="info">recommendations only</Badge>}>
        <div className="space-y-2">
          {recs.map((r, i) => (
            <div key={i} className="rounded-lg border border-white/5 p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-ink-100 flex items-center gap-2"><Zap className="w-4 h-4 text-amber" /> {titleCase(r.action)}</span>
                <ConfidenceBar value={r.confidence} />
              </div>
              <div className="text-xs text-ink-400 mt-1">{r.rationale}</div>
              <div className="text-[10px] text-ink-500 mt-1">Target: {r.target?.display || r.target?.value} · reversible: {String(r.reversible)}</div>
              {can("action:request") && (
                <button className="btn-primary mt-2 !py-1 !text-xs" onClick={() => createAction(r)}>Request action →</button>
              )}
            </div>
          ))}
          {!recs.length && <div className="text-ink-500 text-sm py-6">No recommendations.</div>}
        </div>
      </Panel>

      <Panel title="Response History">
        <div className="space-y-2">
          {data.response_actions.map((a: any) => (
            <div key={a.id} className="rounded-lg border border-white/5 p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-ink-100">{titleCase(a.action_type)}</span>
                <Badge kind="status" value={a.status} />
              </div>
              <div className="text-xs text-ink-500 mt-1">Target: {a.target?.value} · {a.simulated ? "simulated" : "live"}</div>
              {a.verification_result?.verified != null && (
                <div className={cx("text-xs mt-1", a.verification_result.verified ? "text-teal" : "text-crit")}>
                  {a.verification_result.verified ? "✓ verified" : "✗ verification failed"}
                </div>
              )}
            </div>
          ))}
          {!data.response_actions.length && <div className="text-ink-500 text-sm py-6">No response actions yet.</div>}
        </div>
      </Panel>
    </div>
  );
}

function ReportsTab({ incidentId, setToast }: any) {
  const [report, setReport] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const types = ["incident", "executive_summary", "technical_investigation", "root_cause"];

  async function gen(t: string) {
    setBusy(true);
    try {
      const r = await api.post<any>(`/reports`, { report_type: t, incident_id: incidentId });
      setReport(r);
      setToast(`Generated ${titleCase(t)} report.`);
    } catch (e: any) { setToast(e.message); } finally { setBusy(false); }
  }

  return (
    <Panel title="Report Generation" actions={<Badge value="info">facts vs AI inferences distinguished</Badge>}>
      <div className="flex flex-wrap gap-2 mb-4">
        {types.map((t) => (
          <button key={t} className="btn-ghost" disabled={busy} onClick={() => gen(t)}>
            <FileText className="w-4 h-4" /> {titleCase(t)}
          </button>
        ))}
      </div>
      {report && (
        <div className="rounded-lg border border-white/5 p-4">
          <div className="flex items-center justify-between mb-2">
            <h4 className="font-semibold text-ink-100">{report.title}</h4>
            <div className="flex gap-2">
              {["json", "csv", "html", "pdf"].map((f) => (
                <a key={f} className="btn-ghost !py-1 !text-xs" href={`/api/v1/reports/${report.id}/export?format=${f}`} target="_blank" rel="noreferrer">{f.toUpperCase()}</a>
              ))}
            </div>
          </div>
          <p className="text-sm text-ink-400 mb-3">{report.summary}</p>
          {report.content?.sections?.map((s: any, i: number) => (
            <div key={i} className="mb-3">
              <div className="label mb-1">{s.title}</div>
              <div className="text-xs text-ink-300 space-y-0.5">
                {Object.entries(s.fields || {}).map(([k, v]: any) => (
                  <div key={k}><span className="text-ink-500">{k}:</span> {String(v)}</div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
