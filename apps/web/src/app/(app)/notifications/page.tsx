"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useLiveEvents } from "@/lib/store";
import type { Notification } from "@/lib/types";
import { EmptyState, ErrorState, PageHeader, Panel, Skeleton } from "@/components/ui";
import { cx, fmtDate, titleCase } from "@/lib/ui";

const DELIVERY: Record<string, string> = {
  sent: "text-teal", simulated: "text-cyan", not_configured: "text-ink-500", failed: "text-crit", pending: "text-amber",
};

export default function NotificationsPage() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const { data, error, loading, reload } = useApi<{ items: Notification[]; unread: number }>(
    `/notifications?limit=200${unreadOnly ? "&unread=true" : ""}`);
  useLiveEvents((ev) => { if (ev.type === "notification.created") reload(); });

  const markAll = async () => { await api.post("/notifications/read-all"); reload(); };
  const markOne = async (id: string) => { await api.post(`/notifications/${id}/read`); reload(); };

  return (
    <div>
      <PageHeader
        title="Notifications"
        subtitle="SLA breaches, escalations, approvals and platform events for this tenant. Delivery status shows what actually happened on each channel."
        actions={<>
          <label className="text-xs text-ink-400 flex items-center gap-1.5"><input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Unread only</label>
          <button className="btn-ghost" onClick={markAll}><CheckCheck className="w-4 h-4" /> Mark all read</button>
        </>}
      />
      <Panel>
        {error ? <ErrorState message={error.message} /> : loading && !data ? <Skeleton rows={6} /> : !data?.items.length ? <EmptyState label="No notifications." /> : (
          <div className="divide-y divide-white/5">
            {data.items.map((n) => (
              <div key={n.id} className={cx("py-3 flex items-start gap-3", n.read_at && "opacity-70")}>
                <span className={cx("w-2 h-2 rounded-full mt-1.5 shrink-0", n.read_at ? "bg-transparent" : n.level === "critical" ? "bg-crit" : "bg-cyan")} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={cx("text-sm font-medium", n.level === "critical" ? "text-crit" : "text-ink-100")}>{n.title}</span>
                    <span className="chip text-ink-400 border-white/10">{titleCase(n.category)}</span>
                  </div>
                  {n.body && <p className="text-xs text-ink-300 mt-1 whitespace-pre-wrap">{n.body}</p>}
                  <div className="text-[11px] text-ink-500 mt-1 flex flex-wrap gap-3">
                    <span>{fmtDate(n.created_at)}</span>
                    {n.channel && <span>Channel: {n.channel} · <span className={DELIVERY[n.delivery_status || ""] || ""}>{titleCase(n.delivery_status || "n/a")}</span></span>}
                    {n.link?.startsWith("/") && <Link href={n.link} className="text-cyan hover:underline">Open</Link>}
                  </div>
                </div>
                {!n.read_at && <button className="btn-ghost !py-1 !text-xs" onClick={() => markOne(n.id)}>Mark read</button>}
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
