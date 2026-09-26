"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { errorMessage } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { SlaState, SlaTarget } from "@/lib/types";
import { cx } from "@/lib/ui";

export const SLA_COLORS: Record<string, string> = {
  breached: "text-crit border-crit/40 bg-crit/10",
  at_risk: "text-amber border-amber/40 bg-amber/10",
  on_track: "text-teal border-teal/40 bg-teal/10",
  met: "text-ink-300 border-white/10 bg-white/5",
  "n/a": "text-ink-500 border-white/10 bg-white/5",
};

const SLA_LABEL: Record<string, string> = {
  breached: "Breached", at_risk: "At risk", on_track: "On track", met: "Met", "n/a": "No SLA",
};

export function fmtMinutes(m: number | null | undefined): string {
  if (m === null || m === undefined) return "—";
  const neg = m < 0;
  let v = Math.abs(Math.round(m));
  const d = Math.floor(v / 1440);
  v -= d * 1440;
  const h = Math.floor(v / 60);
  const mm = v % 60;
  const s = d ? `${d}d ${h}h` : h ? `${h}h ${mm}m` : `${mm}m`;
  return neg ? `-${s}` : s;
}

export function SlaBadge({ state }: { state: string }) {
  return <span className={cx("chip", SLA_COLORS[state] || SLA_COLORS["n/a"])}>{SLA_LABEL[state] || state}</span>;
}

/** The next SLA clock that matters: acknowledgement until acked, then resolution. */
export function SlaClock({ sla }: { sla?: SlaState }) {
  if (!sla) return <span className="text-ink-500 text-xs">—</span>;
  const pending: [string, SlaTarget][] = [["Ack", sla.ack], ["Resolve", sla.resolve]];
  const next = pending.find(([, t]) => t.minutes_remaining !== null && t.minutes_remaining !== undefined);
  return (
    <div className="flex items-center gap-2">
      <SlaBadge state={sla.overall} />
      {next && (
        <span className={cx("text-xs tabular-nums", (next[1].minutes_remaining ?? 0) < 0 ? "text-crit" : "text-ink-300")}>
          {next[0]} {(next[1].minutes_remaining ?? 0) < 0 ? "overdue " : "in "}
          {fmtMinutes(Math.abs(next[1].minutes_remaining ?? 0))}
        </span>
      )}
      {sla.escalation_level > 0 && (
        <span className="chip text-crit border-crit/40" title="Escalation level">L{sla.escalation_level}</span>
      )}
    </div>
  );
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 1000) / 10}%`;
}

/** Switch into a customer tenant, then navigate (e.g. to an incident). */
export function useOpenInTenant() {
  const { me, switchTenant } = useApp();
  const router = useRouter();
  return useCallback(async (tenantId: string, href: string) => {
    if (me && tenantId !== me.tenant_id) await switchTenant(tenantId);
    router.push(href);
  }, [me, switchTenant, router]);
}

/** Runs an async action and exposes a result banner (success or truthful error). */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const run = useCallback(async (fn: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setResult(null);
    try {
      await fn();
      setResult({ ok: true, message: success });
      return true;
    } catch (e) {
      setResult({ ok: false, message: errorMessage(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, result, run, clear: () => setResult(null) };
}

export function ResultBanner({ result }: { result: { ok: boolean; message: string } | null }) {
  if (!result) return null;
  return (
    <div
      role={result.ok ? "status" : "alert"}
      className={cx(
        "flex items-start gap-2 text-sm rounded-lg border px-3 py-2 mb-3",
        result.ok ? "text-teal border-teal/30 bg-teal/10" : "text-crit border-crit/30 bg-crit/10"
      )}
    >
      {result.ok ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /> : <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />}
      <span>{result.message}</span>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="text-[11px] text-ink-500 mt-0.5 block">{hint}</span>}
    </label>
  );
}

export function currentPeriod(offsetMonths = 0): string {
  const d = new Date();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() + offsetMonths);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function PeriodPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const options = Array.from({ length: 12 }, (_, i) => currentPeriod(-i));
  return (
    <select className="input !w-auto" value={value} onChange={(e) => onChange(e.target.value)} aria-label="Period">
      {options.map((p) => <option key={p} value={p}>{p}</option>)}
    </select>
  );
}
