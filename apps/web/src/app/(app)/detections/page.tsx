"use client";

import { useState } from "react";
import { Play, Plus, Radar } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { useApi, useApp } from "@/lib/store";
import { Badge, DataTable, ErrorState, Modal, PageHeader, Panel, Skeleton } from "@/components/ui";
import { Field, ResultBanner, useAction } from "@/components/mssp";
import { cx, fmtDate, titleCase } from "@/lib/ui";

interface Rule {
  id: string; key: string; name: string; description: string; severity: string; status: string; enabled: boolean;
  version: string; author: string; approved_by: string | null; ai_generated: boolean; trigger_count: number;
  last_triggered_at: string | null; attack_techniques: string[]; sigma: string; matcher: any; exceptions: any[];
  deployment_target: string | null; precision: number | null; recall: number | null; version_history: any[];
}

const LIFECYCLE_COLOR: Record<string, string> = {
  draft: "text-ink-300 border-white/10 bg-white/5", review: "text-amber border-amber/40 bg-amber/10",
  approved: "text-cyan border-cyan/40 bg-cyan/10", deployed: "text-teal border-teal/40 bg-teal/10",
  disabled: "text-ink-500 border-white/10 bg-white/5",
};

const TEMPLATE = JSON.stringify({
  all: [
    { field: "activity", op: "eq", value: "Process create" },
    { field: "cmdline", op: "contains", value: "mimikatz" },
  ],
}, null, 2);

export default function DetectionsPage() {
  const { can } = useApp();
  const list = useApi<{ items: Rule[] }>("/detections?page_size=200");
  const [detail, setDetail] = useState<Rule | null>(null);
  const [creating, setCreating] = useState(false);

  const [replayMsg, setReplayMsg] = useState<string | null>(null);

  const replay = async (r: Rule) => {
    setReplayMsg(null);
    try {
      const res = await api.post<any>(`/detections/${r.id}/replay`);
      setReplayMsg(`Replay of “${r.name}”: ${res.matches} match(es) in ${res.scanned} recent events`
        + (res.labelled
          ? ` · precision ${Math.round(res.precision * 100)}% · recall ${Math.round(res.recall * 100)}%`
          : " · no labelled test data, so precision/recall are not computed")
        + ". Replays do not change live trigger counts.");
      list.reload();
    } catch (e) {
      setReplayMsg(`Replay failed: ${errorMessage(e)}`);
    }
  };

  return (
    <div>
      <PageHeader
        title="Detection Engineering"
        subtitle="Deterministic matchers run on every ingested event. Four-eyes review: authors cannot approve their own rules; AI-drafted rules never deploy without human approval."
        actions={can("detection:write") && <button className="btn-primary" onClick={() => setCreating(true)}><Plus className="w-4 h-4" /> New rule</button>}
      />
      {replayMsg && <div className="mb-3 text-sm text-cyan bg-cyan/10 border border-cyan/30 rounded-lg px-3 py-2">{replayMsg}</div>}
      <Panel>
        {list.error ? <ErrorState message={list.error.message} /> : !list.data ? <Skeleton rows={6} /> : (
          <DataTable<Rule>
            rows={list.data.items}
            onRow={(r) => setDetail(r)}
            empty="No detection rules yet."
            columns={[
              { key: "name", header: "Rule", render: (r) => <div><span className="flex items-center gap-2 text-ink-100"><Radar className="w-4 h-4 text-cyan" /> {r.name}</span><span className="text-[10px] text-ink-500 font-mono">{r.key} · v{r.version}{r.deployment_target?.startsWith("managed:") ? " · managed by provider" : ""}</span></div> },
              { key: "severity", header: "Severity", render: (r) => <Badge kind="severity" value={r.severity} /> },
              { key: "status", header: "Lifecycle", render: (r) => <span className={cx("chip", LIFECYCLE_COLOR[r.status])}>{r.status}{r.status === "deployed" && !r.enabled ? " (off)" : ""}</span> },
              { key: "origin", header: "Origin", render: (r) => <span className="text-xs">{r.ai_generated ? "AI-drafted" : "Authored"} · {r.author}</span> },
              { key: "trigger_count", header: "Live triggers", render: (r) => <span className="tabular-nums">{r.trigger_count || 0}</span> },
              { key: "last", header: "Last fired", render: (r) => <span className="text-xs text-ink-400">{r.last_triggered_at ? fmtDate(r.last_triggered_at) : "—"}</span> },
              { key: "x", header: "", render: (r) => <button className="btn-ghost !py-1 !text-xs" onClick={(e) => { e.stopPropagation(); replay(r); }}><Play className="w-3.5 h-3.5" /> Replay</button> },
            ]}
          />
        )}
      </Panel>
      {creating && <CreateRule onClose={() => setCreating(false)} onDone={() => { setCreating(false); list.reload(); }} />}
      {detail && <RuleDetail rule={detail} onClose={() => setDetail(null)} onChanged={(r) => { setDetail(r); list.reload(); }} />}
    </div>
  );
}

function CreateRule({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const action = useAction();
  const [f, setF] = useState({ name: "", key: "", severity: "medium", description: "", attack: "", sigma: "", matcher: TEMPLATE, fps: "" });
  const [jsonError, setJsonError] = useState<string | null>(null);

  const submit = async () => {
    let matcher: any;
    try { matcher = JSON.parse(f.matcher); setJsonError(null); } catch (e) { setJsonError(errorMessage(e)); return; }
    const ok = await action.run(() => api.post("/detections", {
      name: f.name, key: f.key || undefined, severity: f.severity, description: f.description, sigma: f.sigma, matcher,
      attack_techniques: f.attack.split(",").map((s) => s.trim()).filter(Boolean),
      false_positives: f.fps.split("\n").map((s) => s.trim()).filter(Boolean),
    }), "Draft created. Submit it for review, then a second engineer approves and deploys it.");
    if (ok) onDone();
  };

  return (
    <Modal open onClose={onClose} title="New detection rule" wide>
      <ResultBanner result={action.result} />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
        <Field label="Name"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Key (optional)"><input className="input font-mono" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} placeholder="auto" /></Field>
        <Field label="Severity">
          <select className="input" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}>
            {["critical", "high", "medium", "low", "info"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </select>
        </Field>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
        <Field label="Description"><textarea className="input min-h-16" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="ATT&CK techniques" hint="Comma-separated, e.g. T1003.001, T1059.001"><input className="input font-mono" value={f.attack} onChange={(e) => setF({ ...f, attack: e.target.value })} /></Field>
      </div>
      <Field label="Matcher (JSON — this is what executes)"
        hint='Combine conditions with "all"/"any". Ops: eq, ne, contains, regex, in, gt, gte, lt, lte, exists, threat_intel. Fields: activity, host_name, user_name, src_ip, dst_ip, cmdline, query, target_process, group, or any payload key.'>
        <textarea className={cx("input font-mono text-xs min-h-40", jsonError && "!border-crit")} value={f.matcher} onChange={(e) => setF({ ...f, matcher: e.target.value })} spellCheck={false} />
      </Field>
      {jsonError && <div className="text-xs text-crit mt-1">Invalid JSON: {jsonError}</div>}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
        <Field label="Sigma (documentation / export)"><textarea className="input font-mono text-xs min-h-24" value={f.sigma} onChange={(e) => setF({ ...f, sigma: e.target.value })} /></Field>
        <Field label="Known false positives" hint="One per line."><textarea className="input text-xs min-h-24" value={f.fps} onChange={(e) => setF({ ...f, fps: e.target.value })} /></Field>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={action.busy || !f.name} onClick={submit}>Create draft</button>
      </div>
    </Modal>
  );
}

function RuleDetail({ rule, onClose, onChanged }: { rule: Rule; onClose: () => void; onChanged: (r: Rule) => void }) {
  const { can, me } = useApp();
  const action = useAction();
  const [exceptions, setExceptions] = useState(JSON.stringify(rule.exceptions || [], null, 2));
  const managed = (rule.deployment_target || "").startsWith("managed:");
  const isAuthor = rule.author === me?.email;

  const patch = async (body: any, msg: string) => {
    let updated: Rule | null = null;
    const ok = await action.run(async () => { updated = await api.patch<Rule>(`/detections/${rule.id}`, body); }, msg);
    if (ok && updated) onChanged(updated);
  };
  const saveExceptions = () => {
    let parsed: any;
    try { parsed = JSON.parse(exceptions); } catch { return action.run(async () => { throw new Error("Exceptions must be valid JSON (a list of field→value objects)."); }, ""); }
    return patch({ exceptions: parsed }, "Exceptions saved. Events matching every field of an exception are suppressed.");
  };

  return (
    <Modal open onClose={onClose} title={rule.name} wide>
      <ResultBanner result={action.result} />
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <Badge kind="severity" value={rule.severity} />
        <span className={cx("chip", LIFECYCLE_COLOR[rule.status])}>{rule.status}</span>
        <span className="text-xs text-ink-400">v{rule.version} · author {rule.author}{rule.approved_by ? ` · approved by ${rule.approved_by}` : ""}</span>
        {managed && <span className="chip text-violet border-violet/40">Managed by provider — logic is read-only</span>}
      </div>
      <p className="text-sm text-ink-400 mb-3">{rule.description}</p>

      <div className="flex flex-wrap gap-2 mb-4">
        {can("detection:write") && rule.status === "draft" && !managed && (
          <button className="btn-ghost" onClick={() => patch({ status: "review" }, "Submitted for review.")}>Submit for review</button>
        )}
        {can("detection:approve") && ["draft", "review"].includes(rule.status) && (
          <button className="btn-primary" disabled={isAuthor && !managed} title={isAuthor ? "Another engineer must approve your rule" : undefined}
            onClick={() => patch({ status: "approved" }, "Approved.")}>Approve</button>
        )}
        {can("detection:approve") && rule.status === "approved" && (
          <button className="btn-primary" onClick={() => patch({ status: "deployed" }, "Deployed — the rule now evaluates every ingested event.")}>Deploy</button>
        )}
        {can("detection:write") && rule.status === "deployed" && (
          <button className="btn-ghost" onClick={() => patch({ enabled: !rule.enabled }, rule.enabled ? "Rule switched off." : "Rule switched on.")}>{rule.enabled ? "Switch off" : "Switch on"}</button>
        )}
        {can("detection:write") && rule.status !== "disabled" && (
          <button className="btn-ghost text-crit" onClick={() => patch({ status: "disabled" }, "Rule retired.")}>Retire</button>
        )}
        {can("detection:write") && rule.status === "disabled" && !managed && (
          <button className="btn-ghost" onClick={() => patch({ status: "draft" }, "Back to draft.")}>Reopen as draft</button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <div className="label mb-1">Matcher (executes)</div>
          <pre className="text-xs bg-navy-900 rounded-lg p-3 overflow-x-auto text-ink-300 max-h-64">{JSON.stringify(rule.matcher, null, 2)}</pre>
          <div className="label mt-3 mb-1">Sigma</div>
          <pre className="text-xs bg-navy-900 rounded-lg p-3 overflow-x-auto text-ink-300 max-h-48">{rule.sigma || "(none)"}</pre>
        </div>
        <div>
          <div className="label mb-1">Exceptions (tuning)</div>
          <textarea className="input font-mono text-xs min-h-32" value={exceptions} onChange={(e) => setExceptions(e.target.value)} disabled={!can("detection:write")} spellCheck={false} />
          <div className="text-[11px] text-ink-500 mt-1">e.g. {`[{"host_name": "MGMT-AGENT-01"}]`}. Preserved when your provider redeploys managed content.</div>
          {can("detection:write") && <button className="btn-ghost !py-1 !text-xs mt-2" onClick={saveExceptions}>Save exceptions</button>}
          <div className="label mt-3 mb-1">Quality</div>
          <div className="text-xs text-ink-300">
            Live triggers {rule.trigger_count || 0} · Precision {rule.precision != null ? `${Math.round(rule.precision * 100)}%` : "not measured"} · Recall {rule.recall != null ? `${Math.round(rule.recall * 100)}%` : "not measured"}
          </div>
          <div className="label mt-3 mb-1">Version history</div>
          <ul className="text-xs text-ink-400 space-y-0.5">
            {(rule.version_history || []).slice(-6).reverse().map((v, i) => <li key={i}>v{v.version} · {v.by || v.source || ""} {v.note ? `— ${v.note}` : ""}</li>)}
          </ul>
        </div>
      </div>
    </Modal>
  );
}
