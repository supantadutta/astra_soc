"use client";

import { useEffect, useState } from "react";
import { FlaskConical, ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Badge, Loading, PageHeader, Panel } from "@/components/ui";
import { fmtDate, titleCase } from "@/lib/ui";

export default function LearningPage() {
  const { can } = useApp();
  const [pipeline, setPipeline] = useState<string[]>([]);
  const [feedback, setFeedback] = useState<any>(null);
  const [datasets, setDatasets] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const manage = can("evaluation:manage");

  async function load() {
    if (manage) {
      const [p, f, d, r] = await Promise.all([
        api.get<any>("/learning/pipeline"), api.get<any>("/learning/feedback"),
        api.get<any>("/learning/datasets"), api.get<any>("/learning/runs"),
      ]);
      setPipeline(p.stages); setFeedback(f); setDatasets(d.items); setRuns(r.items);
    }
  }
  useEffect(() => { load(); }, [manage]);

  async function buildDataset() {
    try { await api.post("/learning/datasets/build", {}); setToast("Dataset curated from sanitized feedback."); load(); }
    catch (e: any) { setToast(e.message); }
  }
  async function runEval(dsId: string) {
    try { await api.post("/learning/runs", { dataset_id: dsId, stage: "offline_experiment" }); setToast("Offline experiment complete."); load(); }
    catch (e: any) { setToast(e.message); }
  }
  async function review(id: string) {
    try { await api.post(`/learning/feedback/${id}/review`, { status: "reviewed" }); setToast("Feedback reviewed & sanitized."); load(); }
    catch (e: any) { setToast(e.message); }
  }

  if (!manage) return <div className="text-ink-400 py-16 text-center">The Controlled Learning console requires the <code>evaluation:manage</code> permission (SOC Manager).<br />You can still submit feedback from any incident/agent output.</div>;

  return (
    <div>
      <PageHeader title="Controlled Learning" subtitle="Feedback → review → dataset → offline eval → human approval. The platform never self-modifies production." />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}

      <Panel title="Promotion Pipeline" className="mb-4">
        <div className="flex flex-wrap items-center gap-1.5">
          {pipeline.map((s, i) => (
            <div key={s} className="flex items-center gap-1.5">
              <span className={`chip ${s === "human_approval" ? "text-amber border-amber/40 bg-amber/10" : s === "production" ? "text-teal border-teal/40 bg-teal/10" : "text-ink-300 border-white/10 bg-white/5"}`}>{titleCase(s)}</span>
              {i < pipeline.length - 1 && <ArrowRight className="w-3 h-3 text-ink-500" />}
            </div>
          ))}
        </div>
      </Panel>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Panel title="Analyst Feedback" actions={<button className="btn-ghost !py-1 !text-xs" onClick={buildDataset}>Build dataset →</button>}>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {feedback?.items?.map((f: any) => (
              <div key={f.id} className="rounded-lg border border-white/5 p-2.5 text-sm">
                <div className="flex items-center justify-between">
                  <Badge value={f.kind === "correct" || f.kind === "helpful" ? "healthy" : "unhealthy"}>{titleCase(f.kind)}</Badge>
                  <span className="text-[10px] text-ink-500">{f.review_status}</span>
                </div>
                {f.comment && <p className="text-xs text-ink-400 mt-1">{f.comment}</p>}
                {f.review_status === "raw" && <button className="btn-ghost !py-0.5 !text-[10px] mt-1" onClick={() => review(f.id)}>Review & sanitize</button>}
              </div>
            ))}
            {!feedback?.items?.length && <div className="text-ink-500 text-sm py-6 text-center">No feedback yet. Submit from incident workspaces.</div>}
          </div>
        </Panel>

        <Panel title="Evaluation Datasets">
          <div className="space-y-2">
            {datasets.map((d) => (
              <div key={d.id} className="rounded-lg border border-white/5 p-2.5">
                <div className="flex items-center justify-between text-sm"><span className="text-ink-100">{d.name}</span><span className="text-xs text-ink-500">{d.item_count} items</span></div>
                <button className="btn-ghost !py-0.5 !text-[10px] mt-1" onClick={() => runEval(d.id)}><FlaskConical className="w-3 h-3" /> Run offline experiment</button>
              </div>
            ))}
            {!datasets.length && <div className="text-ink-500 text-sm py-6 text-center">No datasets.</div>}
          </div>
        </Panel>

        <Panel title="Evaluation Runs">
          <div className="space-y-2">
            {runs.map((r) => (
              <div key={r.id} className="rounded-lg border border-white/5 p-2.5 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-ink-100">{r.name}</span>
                  <Badge value={r.passed ? "healthy" : "unhealthy"}>{r.passed ? "passed" : "failed"}</Badge>
                </div>
                <div className="text-xs text-ink-500 mt-0.5">{titleCase(r.stage)} · acc {r.metrics?.accuracy ?? "—"} · {fmtDate(r.created_at)}</div>
                {r.passed && !r.approved_for_production && (
                  <button className="btn-primary !py-0.5 !text-[10px] mt-1" onClick={async () => { await api.post(`/learning/runs/${r.id}/promote`); setToast("Human approval recorded."); load(); }}>Approve for production</button>
                )}
                {r.approved_for_production && <div className="text-[10px] text-teal mt-1">✓ human-approved</div>}
              </div>
            ))}
            {!runs.length && <div className="text-ink-500 text-sm py-6 text-center">No evaluation runs.</div>}
          </div>
        </Panel>
      </div>
    </div>
  );
}
