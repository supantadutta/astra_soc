"use client";

import { useState } from "react";
import { ChevronRight, Play, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useApp, useLiveEvents } from "@/lib/store";
import { Badge, EmptyState, ErrorState, Modal, PageHeader, Panel, Skeleton } from "@/components/ui";
import { Field, ResultBanner, useAction } from "@/components/mssp";
import { cx, fmtDate, timeAgo, titleCase } from "@/lib/ui";

interface Playbook { id: string; key: string; name: string; description: string; enabled: boolean; current_version?: string }
interface Step { id: string; type: string; name?: string; status: string; required_role?: string; result?: any; reason?: string; decided_by?: string; note?: string }
interface Run {
  id: string; playbook_key: string; playbook_version: string; incident_id: string | null; status: string;
  current_step: string | null; step_history: Step[]; error: string | null; created_at: string; finished_at: string | null;
}

const STEP_COLOR: Record<string, string> = {
  done: "text-teal border-teal/40 bg-teal/10", waiting: "text-amber border-amber/40 bg-amber/10",
  failed: "text-crit border-crit/40 bg-crit/10", skipped: "text-ink-500 border-white/10 bg-white/5",
  rejected: "text-crit border-crit/40 bg-crit/10",
};

export default function PlaybooksPage() {
  const { can } = useApp();
  const playbooks = useApi<{ items: Playbook[] }>("/playbooks");
  const runs = useApi<{ items: Run[] }>("/playbooks/runs?page_size=25");
  const action = useAction();
  const [detail, setDetail] = useState<any>(null);
  const [runTarget, setRunTarget] = useState<Playbook | null>(null);
  const [openRun, setOpenRun] = useState<Run | null>(null);

  useLiveEvents((ev) => { if (String(ev.type).startsWith("workflow.")) runs.reload(); });

  const show = async (key: string) => setDetail(await api.get<any>(`/playbooks/${key}`));

  return (
    <div>
      <PageHeader title="Automation Playbooks" subtitle="Durable, versioned workflows with conditions and human approval gates. Runs are started by an analyst (optionally bound to an incident)." />
      <ResultBanner result={action.result} />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Panel title="Playbooks">
          {playbooks.error ? <ErrorState message={playbooks.error.message} /> : !playbooks.data ? <Skeleton rows={4} /> : (
            <div className="space-y-2">
              {!playbooks.data.items.length && <EmptyState label="No playbooks in this tenant." />}
              {playbooks.data.items.map((p) => (
                <div key={p.id} className="rounded-lg border border-white/5 p-3 hover:border-cyan/30 transition-colors">
                  <div className="flex items-center justify-between gap-2">
                    <button onClick={() => show(p.key)} className="flex items-center gap-2 text-sm text-ink-100 text-left">
                      <Workflow className="w-4 h-4 text-cyan" /> {p.name}
                    </button>
                    <div className="flex items-center gap-2">
                      <Badge value={p.enabled ? "healthy" : "not_configured"}>{p.enabled ? "enabled" : "off"}</Badge>
                      {can("playbook:run") && (
                        <button className="btn-primary !py-1 !text-xs" disabled={!p.enabled} onClick={() => setRunTarget(p)}><Play className="w-3.5 h-3.5" /> Run</button>
                      )}
                    </div>
                  </div>
                  <p className="text-xs text-ink-400 mt-1">{p.description}</p>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Recent Runs">
          {runs.error ? <ErrorState message={runs.error.message} /> : !runs.data ? <Skeleton rows={4} /> : (
            <div className="space-y-2">
              {runs.data.items.map((r) => (
                <button key={r.id} onClick={() => setOpenRun(r)} className="w-full text-left rounded-lg border border-white/5 p-3 hover:border-cyan/30">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-ink-100">{titleCase(r.playbook_key)} <span className="text-[10px] text-ink-500">v{r.playbook_version}</span></span>
                    <Badge kind="status" value={r.status === "waiting_approval" ? "pending_approval" : r.status}>{titleCase(r.status)}</Badge>
                  </div>
                  <div className="text-xs text-ink-500 mt-1">
                    {r.step_history?.length || 0} steps · {timeAgo(r.created_at)}
                    {r.status === "waiting_approval" && r.current_step && <span className="text-amber"> · waiting at “{r.current_step}”</span>}
                    {r.error && <span className="text-crit"> · {r.error}</span>}
                  </div>
                </button>
              ))}
              {!runs.data.items.length && <EmptyState label="No runs yet. Start one with Run." />}
            </div>
          )}
        </Panel>
      </div>

      {detail && (
        <Panel title={`${detail.name} — steps`} className="mt-4">
          <div className="flex flex-wrap items-center gap-2">
            {(detail.graph?.steps || []).map((s: any, i: number) => (
              <div key={s.id} className="flex items-center gap-2">
                <span className={cx("chip", s.type === "approval" ? "text-amber border-amber/40 bg-amber/10" : s.type === "response_action" ? "text-crit border-crit/40 bg-crit/10" : "text-ink-200 border-white/10 bg-white/5")}
                  title={s.condition ? `Runs only if: ${JSON.stringify(s.condition)}` : undefined}>
                  {titleCase(s.type)}{s.name ? `: ${s.name}` : ""}{s.condition ? " ⟂" : ""}
                </span>
                {i < detail.graph.steps.length - 1 && <ChevronRight className="w-3.5 h-3.5 text-ink-500" />}
              </div>
            ))}
          </div>
          <p className="text-[11px] text-ink-500 mt-2">⟂ = conditional step. Response-action steps go through the same policy engine and approvals as manual actions.</p>
        </Panel>
      )}

      {runTarget && <RunModal playbook={runTarget} onClose={() => setRunTarget(null)}
        onStarted={(run) => { setRunTarget(null); runs.reload(); setOpenRun(run); }} />}
      {openRun && <RunModal2 run={openRun} onClose={() => setOpenRun(null)} onChanged={(r) => { setOpenRun(r); runs.reload(); }} />}
    </div>
  );
}

function RunModal({ playbook, onClose, onStarted }: { playbook: Playbook; onClose: () => void; onStarted: (r: Run) => void }) {
  const incidents = useApi<{ items: { id: string; key: string; title: string; severity: string }[] }>("/incidents?page_size=50");
  const action = useAction();
  const [incidentId, setIncidentId] = useState("");
  const go = async () => {
    let run: Run | null = null;
    const ok = await action.run(async () => {
      run = await api.post<Run>(`/playbooks/${playbook.key}/run`, { incident_id: incidentId || undefined });
    }, "Run started.");
    if (ok && run) onStarted(run);
  };
  return (
    <Modal open onClose={onClose} title={`Run ${playbook.name}`}>
      <ResultBanner result={action.result} />
      <Field label="Bind to incident (optional)" hint="Steps receive the incident as context; conditions can reference its severity and entities.">
        <select className="input" value={incidentId} onChange={(e) => setIncidentId(e.target.value)}>
          <option value="">No incident</option>
          {incidents.data?.items.map((i) => <option key={i.id} value={i.id}>{i.key} · {i.severity} · {i.title.slice(0, 60)}</option>)}
        </select>
      </Field>
      <div className="flex justify-end gap-2 mt-4">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" onClick={go} disabled={action.busy}><Play className="w-4 h-4" /> Start run</button>
      </div>
    </Modal>
  );
}

function RunModal2({ run, onClose, onChanged }: { run: Run; onClose: () => void; onChanged: (r: Run) => void }) {
  const { can } = useApp();
  const action = useAction();
  const [note, setNote] = useState("");
  const decide = async (decision: "approve" | "reject") => {
    let updated: Run | null = null;
    const ok = await action.run(async () => {
      updated = await api.post<Run>(`/playbooks/runs/${run.id}/resume`, { decision, note });
    }, decision === "approve" ? "Approved — the workflow continued." : "Rejected — the workflow was stopped.");
    if (ok && updated) onChanged(updated);
  };
  const waiting = run.status === "waiting_approval";
  const step = run.step_history?.find((s) => s.status === "waiting" && s.id === run.current_step);
  return (
    <Modal open onClose={onClose} title={`${titleCase(run.playbook_key)} — run`} wide>
      <ResultBanner result={action.result} />
      <div className="text-xs text-ink-400 mb-3">
        Status <b className="text-ink-200">{titleCase(run.status)}</b> · started {fmtDate(run.created_at)}
        {run.finished_at && <> · finished {fmtDate(run.finished_at)}</>}
        {run.incident_id && <> · incident bound</>}
      </div>
      <ol className="space-y-1.5 mb-4">
        {(run.step_history || []).map((s, i) => (
          <li key={i} className="flex items-start gap-2 text-sm border border-white/5 rounded-lg px-3 py-2">
            <span className={cx("chip shrink-0", STEP_COLOR[s.status] || "text-ink-300 border-white/10")}>{s.status}</span>
            <div className="min-w-0">
              <div className="text-ink-100">{titleCase(s.type)}{s.name ? `: ${s.name}` : ""}</div>
              {s.reason && <div className="text-xs text-ink-500">{s.reason}</div>}
              {s.required_role && s.status === "waiting" && <div className="text-xs text-amber">Needs approver role: {titleCase(s.required_role)}</div>}
              {s.result && <div className="text-[11px] text-ink-500 font-mono truncate">{JSON.stringify(s.result)}</div>}
              {s.note && <div className="text-xs text-ink-400">Note: {s.note}</div>}
            </div>
          </li>
        ))}
        {!run.step_history?.length && <li className="text-sm text-ink-500">No steps executed yet.</li>}
      </ol>
      {waiting && can("approval:decide") && (
        <div className="rounded-lg border border-amber/30 bg-amber/5 p-3">
          <div className="text-sm text-amber mb-2">Approval required{step?.name ? `: ${step.name}` : ""}</div>
          <textarea className="input min-h-16 mb-2" placeholder="Decision note (recorded in the audit trail)" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="flex justify-end gap-2">
            <button className="btn-danger" disabled={action.busy} onClick={() => decide("reject")}>Reject</button>
            <button className="btn-primary" disabled={action.busy} onClick={() => decide("approve")}>Approve & continue</button>
          </div>
          <p className="text-[11px] text-ink-500 mt-2">The server checks that your role carries approval authority for this step.</p>
        </div>
      )}
      {waiting && !can("approval:decide") && <p className="text-xs text-amber">Waiting for an approver. You do not hold approval:decide in this tenant.</p>}
    </Modal>
  );
}
