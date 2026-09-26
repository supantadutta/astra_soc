"use client";

import { useEffect, useState } from "react";
import { Building2, Lock, ShieldCheck, ShieldOff } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useApp } from "@/lib/store";
import { ErrorState, Loading, PageHeader, Panel } from "@/components/ui";
import { Field, ResultBanner, fmtMinutes, useAction } from "@/components/mssp";
import { fmtDate, titleCase } from "@/lib/ui";

const PROVIDER_ROLES = ["soc_manager", "incident_commander", "tier3_analyst", "tier2_analyst", "tier1_analyst", "auditor"];

/** The caller's own organization: contract (read-only), escalation contacts,
 * branding and — for customers — control over provider access. */
export default function OrganizationPage() {
  const { me } = useApp();
  const { data, error, reload } = useApi<any>("/tenants/current");
  const action = useAction();
  const [contacts, setContacts] = useState("");
  const [brandName, setBrandName] = useState("");
  const [color, setColor] = useState("");
  const [policy, setPolicy] = useState<any>(null);

  useEffect(() => {
    if (!data) return;
    setContacts((data.contacts || []).map((c: any) => [c.role || "security", c.email, c.phone].filter(Boolean).join(" | ")).join("\n"));
    setBrandName(data.branding?.display_name || "");
    setColor(data.branding?.primary_color || "");
    setPolicy(data.delegation);
  }, [data]);

  if (error) return <ErrorState message={error.message} />;
  if (!data || !policy) return <Loading />;
  const isCustomer = data.kind === "customer";
  const delegated = !!me?.delegated_via;

  const saveProfile = async () => {
    const parsed = contacts.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
      const [role, email, phone] = l.split("|").map((x) => x.trim());
      return { role, email, ...(phone ? { phone } : {}) };
    });
    await action.run(() => api.patch("/tenants/current", {
      contacts: parsed, branding: { ...(data.branding || {}), display_name: brandName || undefined, primary_color: color || undefined },
    }), "Organization profile saved.");
    reload();
  };
  const savePolicy = async (next: any) => {
    const ok = await action.run(() => api.patch("/tenants/current", { delegation: next }),
      next.allow_provider_access ? "Provider access policy saved." : "Provider access switched OFF. Provider staff lose access on their next request.");
    if (ok) { setPolicy(next); reload(); }
  };

  return (
    <div>
      <PageHeader title="Organization" subtitle={`${data.name} · ${titleCase(data.kind)} · ${data.slug}`} />
      <ResultBanner result={action.result} />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <Panel title={<span className="flex items-center gap-2"><Building2 className="w-4 h-4 text-cyan" /> Service contract</span>}>
          <dl className="text-sm space-y-1.5">
            <Row k="Status" v={titleCase(data.status)} />
            <Row k="Service tier" v={titleCase(data.service_tier || "—")} />
            <Row k="Data residency" v={(data.region || "global").toUpperCase()} />
            <Row k="Contract" v={`${data.contract_start ? fmtDate(data.contract_start) : "—"} → ${data.contract_end ? fmtDate(data.contract_end) : "open-ended"}`} />
            <Row k="Included services" v={data.features.includes("*") ? "All (provider)" : data.features.map(titleCase).join(", ")} />
          </dl>
          {isCustomer && data.effective_sla && (
            <>
              <div className="label mt-4 mb-2">Contracted SLA (acknowledge / resolve)</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                {Object.entries(data.effective_sla as Record<string, { ack: number; resolve: number }>).map(([sev, t]) => (
                  <div key={sev} className="rounded-lg border border-white/5 p-2"><div className="text-ink-200">{titleCase(sev)}</div><div className="text-ink-400">{fmtMinutes(t.ack)} / {fmtMinutes(t.resolve)}</div></div>
                ))}
              </div>
            </>
          )}
          <p className="text-[11px] text-ink-500 mt-3">Tier, SLA and entitlements are set by your service provider.</p>
        </Panel>

        {isCustomer && (
          <Panel title={<span className="flex items-center gap-2">{policy.allow_provider_access ? <ShieldCheck className="w-4 h-4 text-teal" /> : <ShieldOff className="w-4 h-4 text-crit" />} Provider access</span>}>
            {delegated ? (
              <p className="text-sm text-ink-400">Only {data.name}&apos;s own administrators can change this policy. You are acting here via your provider.</p>
            ) : (
              <div className="space-y-3">
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={policy.allow_provider_access}
                    onChange={(e) => {
                      if (!e.target.checked && !confirm("Switch off provider access? Your managed SOC will no longer be able to investigate or respond for you. Only audited platform break-glass remains possible.")) return;
                      savePolicy({ ...policy, allow_provider_access: e.target.checked });
                    }} />
                  <span>Allow our managed-security provider to operate in this tenant<span className="block text-xs text-ink-500">All provider actions are attributed to the individual analyst and recorded in your audit log.</span></span>
                </label>
                <Field label="Default role for provider SOC managers">
                  <select className="input" value={policy.default_provider_role} disabled={!policy.allow_provider_access}
                    onChange={(e) => savePolicy({ ...policy, default_provider_role: e.target.value })}>
                    {PROVIDER_ROLES.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
                  </select>
                </Field>
                <Field label="Roles provider staff may be granted" hint="None selected = any non-admin role.">
                  <div className="flex flex-wrap gap-2">
                    {PROVIDER_ROLES.map((r) => (
                      <label key={r} className="flex items-center gap-1 text-xs">
                        <input type="checkbox" disabled={!policy.allow_provider_access} checked={(policy.allowed_roles || []).includes(r)}
                          onChange={(e) => savePolicy({ ...policy, allowed_roles: e.target.checked ? [...(policy.allowed_roles || []), r] : (policy.allowed_roles || []).filter((x: string) => x !== r) })} />
                        {titleCase(r)}
                      </label>
                    ))}
                  </div>
                </Field>
              </div>
            )}
          </Panel>
        )}

        <Panel title={<span className="flex items-center gap-2"><Lock className="w-4 h-4 text-cyan" /> Sign-in security</span>}
          className={isCustomer ? "xl:col-span-2" : ""}>
          <MfaPolicy data={data} delegated={delegated} mfaVerified={!!me?.mfa_verified}
            onSave={async (require_mfa) => {
              const ok = await action.run(() => api.patch("/tenants/current", { security: { require_mfa } }),
                require_mfa ? "Two-step verification is now required for everyone acting in this organization."
                  : "Two-step verification is no longer required.");
              if (ok) reload();
            }} />
        </Panel>

        <Panel title="Escalation contacts & branding" className={isCustomer ? "xl:col-span-2" : ""}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Escalation contacts" hint="One per line: role | email | phone (optional). Used for SLA escalations.">
              <textarea className="input min-h-28 font-mono text-xs" value={contacts} onChange={(e) => setContacts(e.target.value)} placeholder={"security | soc@example.com | +1 555 0100\nciso | ciso@example.com"} />
            </Field>
            <div className="space-y-3">
              <Field label="Display name on reports"><input className="input" value={brandName} onChange={(e) => setBrandName(e.target.value)} placeholder={data.name} /></Field>
              <Field label="Report accent color" hint="Hex, e.g. #0ea5e9"><input className="input" value={color} onChange={(e) => setColor(e.target.value)} pattern="#[0-9a-fA-F]{6}" /></Field>
            </div>
          </div>
          <div className="flex justify-end mt-3"><button className="btn-primary" onClick={saveProfile} disabled={action.busy}>Save</button></div>
        </Panel>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex gap-2"><dt className="text-ink-500 w-36 shrink-0">{k}</dt><dd className="text-ink-200">{v}</dd></div>;
}

function MfaPolicy({ data, delegated, mfaVerified, onSave }: {
  data: any; delegated: boolean; mfaVerified: boolean; onSave: (v: boolean) => void;
}) {
  const required = !!data.security?.require_mfa;
  const setBy = data.security?.require_mfa_set_by;
  if (delegated) {
    return <p className="text-sm text-ink-400">Two-step verification is {required ? "required" : "optional"} here. Only {data.name}&apos;s own administrators can change this.</p>;
  }
  return (
    <div className="space-y-2">
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={required} disabled={!required && !mfaVerified}
          onChange={(e) => {
            if (e.target.checked && !confirm("Require two-step verification for everyone? Users without it must set it up at their next sign-in, and existing sessions without it will end.")) return;
            onSave(e.target.checked);
          }} />
        <span>
          Require two-step verification for everyone acting in this organization
          <span className="block text-xs text-ink-500">
            {data.kind === "customer"
              ? <>Applies to your users <b>and to provider staff</b> entering this tenant, including their API keys. API keys you issue here are not affected.</>
              : <>Applies to every interactive sign-in of your staff. API keys issued in this tenant are not affected.</>}
            {setBy === "provider" && " Currently enforced by your service provider."}
          </span>
        </span>
      </label>
      {!required && !mfaVerified && (
        <p className="text-xs text-amber">Set up two-step verification on your own account (My Account) and sign in with it first, so you cannot lock yourself out.</p>
      )}
    </div>
  );
}
