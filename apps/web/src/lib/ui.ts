/** Shared UI helpers: severity/status color maps, formatting, class merge. */

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export const SEVERITY_COLORS: Record<string, string> = {
  critical: "text-crit border-crit/40 bg-crit/10",
  high: "text-amber border-amber/40 bg-amber/10",
  medium: "text-cyan border-cyan/40 bg-cyan/10",
  low: "text-teal border-teal/40 bg-teal/10",
  info: "text-ink-300 border-white/10 bg-white/5",
};

export const STATUS_COLORS: Record<string, string> = {
  new: "text-cyan border-cyan/40 bg-cyan/10",
  acknowledged: "text-teal border-teal/40 bg-teal/10",
  triaged: "text-teal border-teal/40 bg-teal/10",
  investigating: "text-violet border-violet/40 bg-violet/10",
  escalated: "text-amber border-amber/40 bg-amber/10",
  contained: "text-teal border-teal/40 bg-teal/10",
  resolved: "text-ink-300 border-white/10 bg-white/5",
  closed: "text-ink-400 border-white/10 bg-white/5",
  false_positive: "text-ink-400 border-white/10 bg-white/5",
  pending: "text-amber border-amber/40 bg-amber/10",
  pending_approval: "text-amber border-amber/40 bg-amber/10",
  approved: "text-teal border-teal/40 bg-teal/10",
  auto_approved: "text-teal border-teal/40 bg-teal/10",
  rejected: "text-crit border-crit/40 bg-crit/10",
  blocked_by_policy: "text-crit border-crit/40 bg-crit/10",
  succeeded: "text-teal border-teal/40 bg-teal/10",
  verified: "text-teal border-teal/40 bg-teal/10",
  verify_failed: "text-crit border-crit/40 bg-crit/10",
  failed: "text-crit border-crit/40 bg-crit/10",
  running: "text-cyan border-cyan/40 bg-cyan/10",
  completed: "text-teal border-teal/40 bg-teal/10",
  rolled_back: "text-violet border-violet/40 bg-violet/10",
  healthy: "text-teal border-teal/40 bg-teal/10",
  degraded: "text-amber border-amber/40 bg-amber/10",
  unhealthy: "text-crit border-crit/40 bg-crit/10",
  not_configured: "text-ink-400 border-white/10 bg-white/5",
  unknown: "text-ink-400 border-white/10 bg-white/5",
};

export const EVIDENCE_KIND_META: Record<string, { label: string; color: string; note: string }> = {
  confirmed_fact: { label: "Confirmed Fact", color: "text-teal border-teal/40 bg-teal/10", note: "Verified observation from a source/tool." },
  model_inference: { label: "AI Inference", color: "text-violet border-violet/40 bg-violet/10", note: "Produced by a model — advisory, not confirmed." },
  analyst_conclusion: { label: "Analyst Conclusion", color: "text-cyan border-cyan/40 bg-cyan/10", note: "Reached by a human analyst." },
  assumption: { label: "Assumption", color: "text-amber border-amber/40 bg-amber/10", note: "Working assumption, not yet confirmed." },
  missing_evidence: { label: "Missing Evidence", color: "text-ink-300 border-white/10 bg-white/5", note: "A gap to be filled." },
  recommended_action: { label: "Recommended Action", color: "text-cyan border-cyan/40 bg-cyan/10", note: "Proposed, not executed." },
  executed_action: { label: "Executed Action", color: "text-teal border-teal/40 bg-teal/10", note: "An action that was carried out." },
};

export function colorFor(map: Record<string, string>, key: string): string {
  return map[key] || "text-ink-300 border-white/10 bg-white/5";
}

export function timeAgo(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso).getTime();
  const s = Math.floor((Date.now() - d) / 1000);
  if (s < 0) return "in " + fmtDur(-s);
  return fmtDur(s) + " ago";
}
function fmtDur(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function fmtDate(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function titleCase(s: string): string {
  return s.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function num(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}
