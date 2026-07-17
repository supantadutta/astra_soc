"use client";

import { AlertTriangle, Inbox, Loader2, X } from "lucide-react";
import { cx, colorFor, titleCase, SEVERITY_COLORS, STATUS_COLORS } from "@/lib/ui";

export function Panel({
  title,
  children,
  actions,
  className,
  glow,
}: {
  title?: React.ReactNode;
  children: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  glow?: boolean;
}) {
  return (
    <section className={cx("panel p-4", glow && "shadow-glow", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between mb-3">
          {typeof title === "string" ? <h3 className="card-title">{title}</h3> : title}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Badge({
  children,
  kind = "neutral",
  value,
  map,
}: {
  children?: React.ReactNode;
  kind?: "severity" | "status" | "neutral";
  value?: string;
  map?: Record<string, string>;
}) {
  const chosen =
    kind === "severity"
      ? SEVERITY_COLORS
      : kind === "status"
      ? STATUS_COLORS
      : map || {};
  const cls = value ? colorFor(chosen, value) : "text-ink-300 border-white/10 bg-white/5";
  return (
    <span className={cx("chip", cls)}>{children ?? (value ? titleCase(value) : "")}</span>
  );
}

export function StatTile({
  label,
  value,
  hint,
  accent = "cyan",
  onClick,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  accent?: "cyan" | "violet" | "teal" | "amber" | "crit";
  onClick?: () => void;
}) {
  const accents: Record<string, string> = {
    cyan: "text-cyan",
    violet: "text-violet",
    teal: "text-teal",
    amber: "text-amber",
    crit: "text-crit",
  };
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className={cx(
        "panel p-4 text-left w-full",
        onClick && "panel-hover cursor-pointer"
      )}
    >
      <div className="label">{label}</div>
      <div className={cx("stat-value mt-1", accents[accent])}>{value}</div>
      {hint && <div className="text-xs text-ink-400 mt-1">{hint}</div>}
    </button>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-ink-400 py-10 justify-center">
      <Loader2 className="w-4 h-4 animate-spin" /> {label}
    </div>
  );
}

export function EmptyState({ label = "Nothing here yet.", icon }: { label?: string; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 text-ink-500 py-12">
      {icon ?? <Inbox className="w-8 h-8" />}
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 text-crit py-8 justify-center">
      <AlertTriangle className="w-4 h-4" /> {message}
    </div>
  );
}

export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-9 rounded-lg bg-gradient-to-r from-navy-800 via-navy-700 to-navy-800 bg-[length:800px_100%] animate-shimmer"
        />
      ))}
    </div>
  );
}

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
  className?: string;
}

export function DataTable<T extends { id?: string }>({
  columns,
  rows,
  onRow,
  empty = "No records.",
}: {
  columns: Column<T>[];
  rows: T[];
  onRow?: (row: T) => void;
  empty?: string;
}) {
  if (!rows.length) return <EmptyState label={empty} />;
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm min-w-[640px]">
        <thead>
          <tr className="text-left border-b border-white/5">
            {columns.map((c) => (
              <th key={c.key} className="label py-2 px-2 font-semibold">
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={row.id || i}
              onClick={() => onRow?.(row)}
              className={cx(
                "border-b border-white/5 last:border-0 transition-colors",
                onRow && "cursor-pointer hover:bg-cyan/5"
              )}
            >
              {columns.map((c) => (
                <td key={c.key} className={cx("py-2.5 px-2 text-ink-200", c.className)}>
                  {c.render ? c.render(row) : (row as any)[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-20 bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className={cx("panel w-full max-h-[80vh] overflow-y-auto", wide ? "max-w-3xl" : "max-w-lg")}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between p-4 border-b border-white/5 sticky top-0 bg-navy-800/95 backdrop-blur">
          <h3 className="font-semibold text-ink-100">{title}</h3>
          <button onClick={onClose} className="text-ink-400 hover:text-ink-100" aria-label="Close">
            <X className="w-5 h-5" />
          </button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
      <div>
        <h1 className="text-xl font-bold text-ink-100 tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-ink-400 mt-0.5">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round((value || 0) * 100);
  const color = pct >= 75 ? "bg-teal" : pct >= 50 ? "bg-cyan" : "bg-amber";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 rounded-full bg-white/10 overflow-hidden">
        <div className={cx("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-ink-300">{pct}%</span>
    </div>
  );
}

export function SimBadge() {
  return (
    <span className="chip text-amber border-amber/40 bg-amber/10" title="This result is simulated demo data.">
      SIMULATED
    </span>
  );
}
