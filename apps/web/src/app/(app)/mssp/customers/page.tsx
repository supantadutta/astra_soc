"use client";

import { useState } from "react";
import { Download, Pause, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { api, saveJson } from "@/lib/api";
import { useApi, useApp } from "@/lib/store";
import { Badge, DataTable, ErrorState, Modal, PageHeader, Panel, Skeleton } from "@/components/ui";
import { Field, ResultBanner, useAction, useOpenInTenant } from "@/components/mssp";
import { fmtDate, titleCase } from "@/lib/ui";

interface TenantRow {
  id: string; name: string; slug: string; kind: string; status: string; service_tier: string;
  region: string; parent_id: string | null; contract_start: string | null; contract_end: string | null;
  users: number; provider_access: boolean;
}
interface Catalog {
  tiers: Record<string, { sla: Record<string, { ack: number; resolve: number }>; features: string[] }>;
  features: Record<string, string>;
  statuses: string[];
}

const STATUS_MAP: Record<string, string> = {
  active: "text-teal border-teal/40 bg-teal/10",
  onboarding: "text-cyan border-cyan/40 bg-cyan/10",
  suspended: "text-amber border-amber/40 bg-amber/10",
  offboarding: "text-crit border-crit/40 bg-crit/10",
};
const REGIONS = ["global", "us", "eu", "uk", "apac", "in", "me"];

export default function CustomersPage() {
  const { canHome, me } = useApp();
  const openIn = useOpenInTenant();
  const list = useApi<{ items: TenantRow[] }>("/mssp/tenants");
  const catalog = useApi<Catalog>("/mssp/catalog");
  const action = useAction();
  const [onboarding, setOnboarding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [offboard, setOffboard] = useState<TenantRow | null>(null);
  const canManage = canHome("mssp:onboard");

  const rows = (list.data?.items || []).filter((t) => t.id !== me?.home_tenant_id);
  const parents = (list.data?.items || []).filter((t) => t.kind !== "customer");

  const lifecycle = async (t: TenantRow, verb: "suspend" | "activate") => {
    if (verb === "suspend" && !confirm(`Suspend ${t.name}? Its users will be signed out on their next request.`)) return;
    await action.run(() => api.post(`/mssp/tenants/${t.id}/${verb}`, verb === "suspend" ? { reason: "Suspended from console" } : undefined),
      `${t.name} ${verb === "suspend" ? "suspended" : "activated"}.`);
    list.reload();
  };
  const exportTenant = async (t: TenantRow) => {
    await action.run(async () => saveJson(await api.get(`/mssp/tenants/${t.id}/export`), `${t.slug}-export.json`),
      `Export of ${t.name} downloaded (credentials and password hashes are never included).`);
  };

  return (
    <div>
      <PageHeader
        title="Customers"
        subtitle="Onboard customers and resellers, manage service tiers, contracts and lifecycle."
        actions={canManage && <button className="btn-primary" onClick={() => setOnboarding(true)}><Plus className="w-4 h-4" /> Onboard customer</button>}
      />
      <ResultBanner result={action.result} />
      <Panel>
        {list.error ? <ErrorState message={list.error.message} /> : list.loading && !list.data ? <Skeleton rows={6} /> : (
          <DataTable<TenantRow>
            rows={rows}
            empty="No customers yet."
            columns={[
              { key: "name", header: "Customer", render: (t) => (
                <div>
                  <button className="text-ink-100 hover:text-cyan text-left" onClick={() => openIn(t.id, "/dashboard")} disabled={!t.provider_access}
                    title={t.provider_access ? "Open this customer's SOC" : "Provider access is switched off by the customer"}>
                    {t.name}
                  </button>
                  <div className="text-[10px] text-ink-500 font-mono">{t.slug}{t.parent_id && t.parent_id !== me?.home_tenant_id ? " · via reseller" : ""}</div>
                </div>) },
              { key: "kind", header: "Type", render: (t) => titleCase(t.kind) },
              { key: "tier", header: "Tier", render: (t) => titleCase(t.service_tier) },
              { key: "region", header: "Region", render: (t) => t.region.toUpperCase() },
              { key: "status", header: "Status", render: (t) => <Badge value={t.status} map={STATUS_MAP} /> },
              { key: "contract", header: "Contract", render: (t) => <span className="text-xs text-ink-400">{t.contract_start ? fmtDate(t.contract_start) : "—"} → {t.contract_end ? fmtDate(t.contract_end) : "open"}</span> },
              { key: "users", header: "Users" },
              { key: "access", header: "Provider access", render: (t) => t.provider_access ? <span className="text-teal text-xs">allowed</span> : <span className="text-crit text-xs">revoked by customer</span> },
              { key: "actions", header: "", render: (t) => canManage && (
                <div className="flex items-center gap-1 justify-end" onClick={(e) => e.stopPropagation()}>
                  <button className="btn-ghost !px-2 !py-1" title="Edit contract" onClick={() => setEditing(t.id)}><Pencil className="w-3.5 h-3.5" /></button>
                  {t.status === "suspended"
                    ? <button className="btn-ghost !px-2 !py-1" title="Activate" onClick={() => lifecycle(t, "activate")}><Play className="w-3.5 h-3.5" /></button>
                    : <button className="btn-ghost !px-2 !py-1" title="Suspend" onClick={() => lifecycle(t, "suspend")}><Pause className="w-3.5 h-3.5" /></button>}
                  <button className="btn-ghost !px-2 !py-1" title="Export tenant data" onClick={() => exportTenant(t)}><Download className="w-3.5 h-3.5" /></button>
                  <button className="btn-ghost !px-2 !py-1 text-crit" title="Offboard (purge)" onClick={() => setOffboard(t)}
                    disabled={!["suspended", "offboarding"].includes(t.status)}><Trash2 className="w-3.5 h-3.5" /></button>
                </div>) },
            ]}
          />
        )}
      </Panel>

      {onboarding && catalog.data && (
        <OnboardModal catalog={catalog.data} parents={parents} homeId={me?.home_tenant_id || ""}
          onClose={() => setOnboarding(false)} onDone={() => { setOnboarding(false); list.reload(); }} />
      )}
      {editing && catalog.data && (
        <EditModal id={editing} catalog={catalog.data} onClose={() => setEditing(null)} onDone={() => { setEditing(null); list.reload(); }} />
      )}
      {offboard && (
        <OffboardModal tenant={offboard} onClose={() => setOffboard(null)} onDone={() => { setOffboard(null); list.reload(); }} />
      )}
    </div>
  );
}

function OnboardModal({ catalog, parents, homeId, onClose, onDone }: {
  catalog: Catalog; parents: TenantRow[]; homeId: string; onClose: () => void; onDone: () => void;
}) {
  const action = useAction();
  const [f, setF] = useState({
    name: "", slug: "", kind: "customer", parent_id: homeId, service_tier: "professional", region: "global",
    status: "onboarding", contract_start: "", contract_end: "", contact_email: "",
    admin_email: "", admin_name: "", admin_password: "",
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value, ...(k === "name" && !f.slug ? {} : {}) });
  const autoSlug = f.slug || f.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = await action.run(() => api.post("/mssp/tenants", {
      name: f.name, slug: autoSlug, kind: f.kind, parent_id: f.parent_id || undefined,
      service_tier: f.service_tier, region: f.region, status: f.status,
      contract_start: f.contract_start || undefined, contract_end: f.contract_end || undefined,
      contacts: f.contact_email ? [{ role: "security", email: f.contact_email }] : undefined,
      admin: f.admin_email ? { email: f.admin_email, full_name: f.admin_name, password: f.admin_password } : undefined,
    }), `${f.name} onboarded.`);
    if (ok) onDone();
  };
  const tier = catalog.tiers[f.service_tier];

  return (
    <Modal open onClose={onClose} title="Onboard customer" wide>
      <form onSubmit={submit} className="space-y-4">
        <ResultBanner result={action.result} />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Organization name"><input className="input" required value={f.name} onChange={set("name")} /></Field>
          <Field label="Slug" hint="Lowercase identifier; also the vault:// secret namespace."><input className="input font-mono" value={autoSlug} onChange={set("slug")} pattern="[a-z0-9][a-z0-9-]{1,39}" /></Field>
          <Field label="Type">
            <select className="input" value={f.kind} onChange={set("kind")}>
              <option value="customer">Customer</option><option value="reseller">Reseller / partner</option>
            </select>
          </Field>
          <Field label="Managed by">
            <select className="input" value={f.parent_id} onChange={set("parent_id")}>
              {parents.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.kind})</option>)}
            </select>
          </Field>
          <Field label="Service tier">
            <select className="input" value={f.service_tier} onChange={set("service_tier")}>
              {Object.keys(catalog.tiers).map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
            </select>
          </Field>
          <Field label="Data residency region">
            <select className="input" value={f.region} onChange={set("region")}>
              {REGIONS.map((r) => <option key={r} value={r}>{r.toUpperCase()}</option>)}
            </select>
          </Field>
          <Field label="Initial status">
            <select className="input" value={f.status} onChange={set("status")}>
              <option value="onboarding">Onboarding</option><option value="active">Active</option>
            </select>
          </Field>
          <Field label="Security contact email"><input className="input" type="email" value={f.contact_email} onChange={set("contact_email")} /></Field>
          <Field label="Contract start"><input className="input" type="date" value={f.contract_start} onChange={set("contract_start")} /></Field>
          <Field label="Contract end"><input className="input" type="date" value={f.contract_end} onChange={set("contract_end")} /></Field>
        </div>
        {tier && (
          <div className="rounded-lg border border-white/5 bg-navy-900/60 p-3 text-xs text-ink-300">
            <div className="label mb-1">{titleCase(f.service_tier)} includes</div>
            <div className="flex flex-wrap gap-1 mb-2">{tier.features.map((x) => <span key={x} className="chip text-ink-200 border-white/10">{titleCase(x)}</span>)}</div>
            <div className="label mb-1">Default SLA (ack / resolve)</div>
            <div className="flex flex-wrap gap-3">{Object.entries(tier.sla).map(([sev, t]) => <span key={sev}>{titleCase(sev)}: {t.ack}m / {Math.round(t.resolve / 60)}h</span>)}</div>
          </div>
        )}
        <div>
          <div className="label mb-2">First administrator (optional)</div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Field label="Email"><input className="input" type="text" value={f.admin_email} onChange={set("admin_email")} /></Field>
            <Field label="Full name"><input className="input" value={f.admin_name} onChange={set("admin_name")} /></Field>
            <Field label="Temporary password" hint="Min 12 chars, mixed character classes."><input className="input" type="password" autoComplete="new-password" value={f.admin_password} onChange={set("admin_password")} /></Field>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={action.busy || !f.name}>{action.busy ? "Onboarding…" : "Onboard"}</button>
        </div>
      </form>
    </Modal>
  );
}

function EditModal({ id, catalog, onClose, onDone }: { id: string; catalog: Catalog; onClose: () => void; onDone: () => void }) {
  const { data, error } = useApi<any>(`/mssp/tenants/${id}`);
  const action = useAction();
  const [draft, setDraft] = useState<any>(null);
  if (error) return <Modal open onClose={onClose} title="Edit contract"><ErrorState message={error.message} /></Modal>;
  if (!data) return <Modal open onClose={onClose} title="Edit contract"><Skeleton rows={4} /></Modal>;
  const d = draft || {
    service_tier: data.service_tier, status: data.status, region: data.region,
    contract_start: data.contract_start?.slice(0, 10) || "", contract_end: data.contract_end?.slice(0, 10) || "",
    feature_overrides: data.settings?.feature_overrides || {},
    sla_policy: data.sla_policy || {},
    customer_approval_actions: (data.settings?.customer_approval_actions || []).join(", "),
  };
  const upd = (patch: any) => setDraft({ ...d, ...patch });
  const tierFeatures = new Set(catalog.tiers[d.service_tier]?.features || []);
  const tierSla = catalog.tiers[d.service_tier]?.sla || {};

  const save = async () => {
    const sla: Record<string, Record<string, number>> = {};
    for (const [sev, t] of Object.entries(d.sla_policy as Record<string, any>)) {
      const clean: Record<string, number> = {};
      for (const k of ["ack", "resolve"]) if (t?.[k]) clean[k] = Number(t[k]);
      if (Object.keys(clean).length) sla[sev] = clean;
    }
    const ok = await action.run(() => api.patch(`/mssp/tenants/${id}`, {
      service_tier: d.service_tier, status: d.status, region: d.region,
      contract_start: d.contract_start || null, contract_end: d.contract_end || null,
      feature_overrides: d.feature_overrides, sla_policy: sla,
      customer_approval_actions: String(d.customer_approval_actions).split(",").map((s) => s.trim()).filter(Boolean),
    }), "Contract updated. The change is recorded in both your and the customer's audit trail.");
    if (ok) onDone();
  };

  return (
    <Modal open onClose={onClose} title={`Contract — ${data.name}`} wide>
      <ResultBanner result={action.result} />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <Field label="Service tier">
          <select className="input" value={d.service_tier} onChange={(e) => upd({ service_tier: e.target.value })}>
            {Object.keys(catalog.tiers).map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
          </select>
        </Field>
        <Field label="Status">
          <select className="input" value={d.status} onChange={(e) => upd({ status: e.target.value })}>
            {catalog.statuses.map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </select>
        </Field>
        <Field label="Region">
          <select className="input" value={d.region} onChange={(e) => upd({ region: e.target.value })}>
            {REGIONS.map((r) => <option key={r} value={r}>{r.toUpperCase()}</option>)}
          </select>
        </Field>
        <Field label="Contract start"><input type="date" className="input" value={d.contract_start} onChange={(e) => upd({ contract_start: e.target.value })} /></Field>
        <Field label="Contract end"><input type="date" className="input" value={d.contract_end} onChange={(e) => upd({ contract_end: e.target.value })} /></Field>
      </div>

      <div className="label mb-2">Feature entitlements</div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5 mb-4">
        {Object.entries(catalog.features).map(([key, desc]) => {
          const override = d.feature_overrides[key];
          const effective = override === undefined ? tierFeatures.has(key) : !!override;
          return (
            <div key={key} className="flex items-center gap-2 text-xs rounded-lg border border-white/5 px-2 py-1.5">
              <select className="input !w-28 !py-1 !text-xs" value={override === undefined ? "tier" : override ? "on" : "off"}
                onChange={(e) => {
                  const next = { ...d.feature_overrides };
                  if (e.target.value === "tier") delete next[key];
                  else next[key] = e.target.value === "on";
                  upd({ feature_overrides: next });
                }}>
                <option value="tier">Tier default</option><option value="on">Force on</option><option value="off">Force off</option>
              </select>
              <span className={effective ? "text-teal" : "text-ink-500"}>{effective ? "●" : "○"}</span>
              <span className="text-ink-200" title={desc}>{titleCase(key)}</span>
            </div>
          );
        })}
      </div>

      <div className="label mb-2">SLA overrides (minutes; blank = tier default)</div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
        {Object.entries(tierSla).map(([sev, def]) => (
          <div key={sev} className="rounded-lg border border-white/5 p-2 text-xs">
            <div className="text-ink-200 mb-1">{titleCase(sev)}</div>
            {(["ack", "resolve"] as const).map((k) => (
              <label key={k} className="flex items-center gap-1 mb-1">
                <span className="w-12 text-ink-500">{k}</span>
                <input className="input !py-1 !text-xs" type="number" min={1} placeholder={String(def[k])}
                  value={d.sla_policy?.[sev]?.[k] ?? ""}
                  onChange={(e) => upd({ sla_policy: { ...d.sla_policy, [sev]: { ...(d.sla_policy?.[sev] || {}), [k]: e.target.value ? Number(e.target.value) : undefined } } })} />
              </label>
            ))}
          </div>
        ))}
      </div>

      <Field label="Actions requiring customer approval" hint="Comma-separated response action types (e.g. isolate_host, disable_user). Recorded on the contract for reference only; the response gateway does not enforce it yet (see Known Limitations).">
        <input className="input" value={d.customer_approval_actions} onChange={(e) => upd({ customer_approval_actions: e.target.value })} />
      </Field>

      <div className="flex justify-end gap-2 mt-4">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" onClick={save} disabled={action.busy}>{action.busy ? "Saving…" : "Save contract"}</button>
      </div>
    </Modal>
  );
}

function OffboardModal({ tenant, onClose, onDone }: { tenant: TenantRow; onClose: () => void; onDone: () => void }) {
  const [confirmText, setConfirm] = useState("");
  const action = useAction();
  const go = async () => {
    const ok = await action.run(() => api.del(`/mssp/tenants/${tenant.id}`, { confirm: confirmText }), `${tenant.name} offboarded.`);
    if (ok) onDone();
  };
  return (
    <Modal open onClose={onClose} title={`Offboard ${tenant.name}`}>
      <ResultBanner result={action.result} />
      <p className="text-sm text-ink-300 mb-3">
        This permanently deletes the customer&apos;s users, incidents, alerts, evidence, connectors and configuration.
        Audit records are retained. Export the tenant first if the contract requires a data hand-back.
      </p>
      <Field label={`Type ${tenant.slug} to confirm`}>
        <input className="input font-mono" value={confirmText} onChange={(e) => setConfirm(e.target.value)} />
      </Field>
      <div className="flex justify-end gap-2 mt-4">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-danger" disabled={confirmText !== tenant.slug || action.busy} onClick={go}>Offboard permanently</button>
      </div>
    </Modal>
  );
}
