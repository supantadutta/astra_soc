"use client";

import { useRouter } from "next/navigation";
import { Building2, RefreshCw } from "lucide-react";
import { useApi, useLiveEvents } from "@/lib/store";
import { ErrorState, Loading, PageHeader, Panel, StatTile } from "@/components/ui";
import { SLA_COLORS, useOpenInTenant } from "@/components/mssp";
import { cx, num, timeAgo, titleCase } from "@/lib/ui";

interface Card {
  id: string; name: string; slug: string; kind: string; status: string; service_tier: string;
  region: string; mode: string; open_incidents: number; by_severity: Record<string, number>;
  sla_breached: number; sla_at_risk: number; pending_approvals: number; enabled_connectors: number;
  unhealthy_connectors: number; last_activity: string | null; contract_end: string | null;
  provider_access: boolean; health_score: number;
}

export default function PortfolioPage() {
  const router = useRouter();
  const open = useOpenInTenant();
  const { data, error, loading, reload } = useApi<{ customers: Card[]; totals: Record<string, number> }>("/mssp/overview");

  useLiveEvents((ev) => {
    if (ev.type === "incident.created" || ev.type === "approval.decided") reload();
  });

  if (loading && !data) return <Loading label="Loading portfolio…" />;
  if (error) return <ErrorState message={error.message} />;
  if (!data) return null;
  const t = data.totals;

  return (
    <div>
      <PageHeader
        title="Managed Service Portfolio"
        subtitle="Every customer you are responsible for, worst first. Figures are computed live from each customer's own data."
        actions={<button className="btn-ghost" onClick={reload}><RefreshCw className="w-4 h-4" /> Refresh</button>}
      />

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-7 gap-3 mb-5">
        <StatTile label="Customers" value={num(t.customers)} onClick={() => router.push("/mssp/customers")} />
        <StatTile label="Open incidents" value={num(t.open_incidents)} onClick={() => router.push("/mssp/queue")} />
        <StatTile label="Critical open" value={num(t.critical_open)} accent="crit" onClick={() => router.push("/mssp/queue")} />
        <StatTile label="SLA breached" value={num(t.sla_breached)} accent="crit" onClick={() => router.push("/mssp/queue")} />
        <StatTile label="SLA at risk" value={num(t.sla_at_risk)} accent="amber" onClick={() => router.push("/mssp/queue")} />
        <StatTile label="Pending approvals" value={num(t.pending_approvals)} accent="violet" />
        <StatTile label="Unhealthy connectors" value={num(t.unhealthy_connectors)} accent="amber" />
      </div>

      {!data.customers.length ? (
        <Panel><div className="text-center text-ink-400 py-10 text-sm">No customers in your portfolio yet. Onboard one from <b>Customers</b>.</div></Panel>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {data.customers.map((c) => (
            <button
              key={c.id}
              onClick={() => open(c.id, "/dashboard")}
              disabled={!c.provider_access}
              className="panel panel-hover p-4 text-left disabled:opacity-60 disabled:cursor-not-allowed"
              title={c.provider_access ? `Open ${c.name}'s SOC` : "The customer has switched off provider access"}
            >
              <div className="flex items-start gap-3">
                <HealthRing score={c.health_score} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Building2 className="w-4 h-4 text-ink-500 shrink-0" />
                    <span className="font-semibold text-ink-100 truncate">{c.name}</span>
                  </div>
                  <div className="text-[11px] text-ink-500 mt-0.5">
                    {titleCase(c.service_tier)} · {c.region.toUpperCase()} · {c.mode}
                    {c.status !== "active" && <span className="text-amber"> · {c.status}</span>}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-2 mt-3 text-center">
                <Mini label="Open" value={c.open_incidents} />
                <Mini label="Critical" value={c.by_severity.critical || 0} cls={c.by_severity.critical ? "text-crit" : ""} />
                <Mini label="Breached" value={c.sla_breached} cls={c.sla_breached ? "text-crit" : ""} />
                <Mini label="At risk" value={c.sla_at_risk} cls={c.sla_at_risk ? "text-amber" : ""} />
              </div>

              <div className="flex flex-wrap items-center gap-2 mt-3 text-[11px] text-ink-400">
                <span>{c.enabled_connectors} connectors{c.unhealthy_connectors ? <b className="text-amber"> ({c.unhealthy_connectors} unhealthy)</b> : null}</span>
                <span>· {c.pending_approvals} approvals</span>
                <span>· active {timeAgo(c.last_activity || undefined)}</span>
                {!c.provider_access && <span className={cx("chip", SLA_COLORS.breached)}>Provider access off</span>}
                {c.contract_end && new Date(c.contract_end).getTime() - Date.now() < 60 * 864e5 && (
                  <span className="chip text-amber border-amber/40">Contract ends {new Date(c.contract_end).toLocaleDateString()}</span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
      <p className="text-[11px] text-ink-500 mt-4">
        Health score = 100 − 25×SLA breaches − 10×critical − 5×high − 5×unhealthy connectors. It is a triage aid, not a contractual KPI.
      </p>
    </div>
  );
}

function Mini({ label, value, cls }: { label: string; value: number; cls?: string }) {
  return (
    <div className="rounded-lg bg-navy-900/60 border border-white/5 py-1.5">
      <div className={cx("text-lg font-bold tabular-nums text-ink-100", cls)}>{value}</div>
      <div className="text-[10px] text-ink-500 uppercase tracking-wide">{label}</div>
    </div>
  );
}

function HealthRing({ score }: { score: number }) {
  const color = score >= 80 ? "#2dd4bf" : score >= 50 ? "#f59e0b" : "#f43f5e";
  const r = 18;
  const c = 2 * Math.PI * r;
  return (
    <svg width="46" height="46" viewBox="0 0 46 46" className="shrink-0" aria-label={`Health ${score}`}>
      <circle cx="23" cy="23" r={r} stroke="rgba(255,255,255,0.08)" strokeWidth="4" fill="none" />
      <circle cx="23" cy="23" r={r} stroke={color} strokeWidth="4" fill="none" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} transform="rotate(-90 23 23)" />
      <text x="23" y="27" textAnchor="middle" fontSize="12" fontWeight="700" fill={color}>{score}</text>
    </svg>
  );
}
