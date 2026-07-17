"use client";

import { useEffect, useState } from "react";
import { Layers } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Loading, PageHeader, Panel } from "@/components/ui";
import { fmtDate } from "@/lib/ui";

export default function TenantsPage() {
  const [items, setItems] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.get<any>("/tenants").then((r) => setItems(r.items)).catch((e) => setErr(e.message));
  }, []);

  if (err) return <div className="text-crit py-16 text-center">Access denied: {err}. Tenant management requires tenant:manage (platform super admin).</div>;
  if (!items) return <Loading />;

  return (
    <div>
      <PageHeader title="Tenant Management" subtitle="Isolated tenants — data, cases, embeddings and model context never cross" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {items.map((t) => (
          <Panel key={t.id} title={<span className="flex items-center gap-2"><Layers className="w-4 h-4 text-cyan" /> {t.name}</span>}
            actions={<Badge value={t.is_active ? "healthy" : "not_configured"}>{t.is_active ? "active" : "inactive"}</Badge>}>
            <div className="text-xs text-ink-400 space-y-1">
              <div>Slug: <span className="font-mono text-ink-200">{t.slug}</span></div>
              <div>Created: {fmtDate(t.created_at)}</div>
              <div>Daily token budget: {t.settings?.daily_token_budget?.toLocaleString?.() || "unlimited"}</div>
              <div>Monthly cost limit: ${t.settings?.monthly_cost_limit_usd || "—"}</div>
              <div>Private-model-only: {String(t.settings?.private_model_only ?? false)}</div>
            </div>
          </Panel>
        ))}
      </div>
    </div>
  );
}
