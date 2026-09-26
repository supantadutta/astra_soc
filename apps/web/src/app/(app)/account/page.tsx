"use client";

import { useState } from "react";
import { Copy, KeyRound, LogOut, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useApp } from "@/lib/store";
import { DataTable, ErrorState, Modal, PageHeader, Panel, Skeleton } from "@/components/ui";
import { Field, ResultBanner, useAction } from "@/components/mssp";
import { fmtDate, timeAgo, titleCase } from "@/lib/ui";

interface Sess { id: string; ip_address: string | null; user_agent: string | null; created_at: string; expires_at: string; last_used_at: string | null; revoked: boolean; revoked_reason: string | null; current: boolean }
interface Key { id: string; name: string; prefix: string; scopes: string[]; expires_at: string | null; revoked: boolean; last_used_at: string | null }

export default function AccountPage() {
  const { me, can } = useApp();
  const sessions = useApi<{ items: Sess[] }>("/auth/sessions");
  const keys = useApi<{ items: Key[] }>(can("user:manage") ? "/auth/api-keys" : null);
  const action = useAction();
  const [pw, setPw] = useState({ current_password: "", new_password: "", confirm: "" });
  const [newKey, setNewKey] = useState(false);

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw.new_password !== pw.confirm) return;
    const ok = await action.run(() => api.post("/auth/password", { current_password: pw.current_password, new_password: pw.new_password }),
      "Password changed. All your other sessions were signed out.");
    if (ok) { setPw({ current_password: "", new_password: "", confirm: "" }); sessions.reload(); }
  };
  const revokeSession = async (s: Sess) => { await action.run(() => api.post(`/auth/sessions/${s.id}/revoke`), "Session revoked."); sessions.reload(); };
  const revokeKey = async (k: Key) => {
    if (!confirm(`Revoke API key “${k.name}”? Integrations using it stop working immediately.`)) return;
    await action.run(() => api.post(`/auth/api-keys/${k.id}/revoke`), "API key revoked."); keys.reload();
  };

  if (!me) return null;
  return (
    <div>
      <PageHeader title="My Account" subtitle={`${me.full_name} · ${me.email}`} />
      <ResultBanner result={action.result} />
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mb-3">
        <Panel title="Identity">
          <dl className="text-sm space-y-1.5">
            <Row k="Home organization" v={me.home_tenant_slug} />
            <Row k="Acting in" v={`${me.tenant_name} (${titleCase(me.tenant_kind)})`} />
            <Row k="Roles here" v={me.roles.map(titleCase).join(", ")} />
            {me.delegated_via && <Row k="Access path" v={titleCase(me.delegated_via)} />}
            <Row k="Permissions here" v={`${me.permissions.length}`} />
          </dl>
        </Panel>
        <Panel title="Change password" className="xl:col-span-2">
          <form onSubmit={changePassword} className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
            <Field label="Current password"><input className="input" type="password" autoComplete="current-password" required value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
            <Field label="New password" hint="12+ characters, mixed classes."><input className="input" type="password" autoComplete="new-password" required value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
            <Field label="Confirm" hint={pw.confirm && pw.confirm !== pw.new_password ? "Does not match." : undefined}><input className="input" type="password" autoComplete="new-password" required value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} /></Field>
            <div className="md:col-span-3 flex justify-end"><button className="btn-primary" disabled={action.busy || !pw.new_password || pw.new_password !== pw.confirm}>Change password</button></div>
          </form>
        </Panel>
      </div>

      <Panel title="Active sessions" className="mb-3">
        {sessions.error ? <ErrorState message={sessions.error.message} /> : !sessions.data ? <Skeleton rows={3} /> : (
          <DataTable<Sess>
            rows={sessions.data.items}
            columns={[
              { key: "ua", header: "Device", render: (s) => <div className="max-w-md"><div className="truncate text-xs">{s.user_agent || "unknown client"}</div>{s.current && <span className="text-[10px] text-teal">this session</span>}</div> },
              { key: "ip", header: "IP", render: (s) => <span className="font-mono text-xs">{s.ip_address || "—"}</span> },
              { key: "created", header: "Signed in", render: (s) => <span className="text-xs">{fmtDate(s.created_at)}</span> },
              { key: "used", header: "Last used", render: (s) => <span className="text-xs">{timeAgo(s.last_used_at || s.created_at)}</span> },
              { key: "state", header: "State", render: (s) => s.revoked ? <span className="text-xs text-ink-500">revoked · {s.revoked_reason}</span> : new Date(s.expires_at) < new Date() ? <span className="text-xs text-ink-500">expired</span> : <span className="text-xs text-teal">active</span> },
              { key: "x", header: "", render: (s) => !s.revoked && !s.current && new Date(s.expires_at) > new Date() && (
                <button className="btn-ghost !py-1 !text-xs" onClick={() => revokeSession(s)}><LogOut className="w-3.5 h-3.5" /> Sign out</button>) },
            ]}
          />
        )}
      </Panel>

      {can("user:manage") && (
        <Panel title="API keys (this tenant)" actions={<button className="btn-primary !py-1 !text-xs" onClick={() => setNewKey(true)}><Plus className="w-3.5 h-3.5" /> New key</button>}>
          {keys.error ? <ErrorState message={keys.error.message} /> : !keys.data ? <Skeleton rows={3} /> : (
            <DataTable<Key>
              rows={keys.data.items}
              empty="No API keys. Create one for SIEM forwarders or automation (scoped, expiring)."
              columns={[
                { key: "name", header: "Name", render: (k) => <div><div className="text-ink-100">{k.name}</div><div className="font-mono text-[10px] text-ink-500">{k.prefix}…</div></div> },
                { key: "scopes", header: "Scopes", render: (k) => <span className="text-xs text-ink-300">{k.scopes.join(", ")}</span> },
                { key: "exp", header: "Expires", render: (k) => <span className="text-xs">{k.expires_at ? fmtDate(k.expires_at) : "—"}</span> },
                { key: "used", header: "Last used", render: (k) => <span className="text-xs">{k.last_used_at ? timeAgo(k.last_used_at) : "never"}</span> },
                { key: "x", header: "", render: (k) => k.revoked ? <span className="text-xs text-ink-500">revoked</span> : <button className="btn-ghost !py-1 !text-xs text-crit" onClick={() => revokeKey(k)}>Revoke</button> },
              ]}
            />
          )}
        </Panel>
      )}
      {newKey && <NewKeyModal permissions={me.permissions} onClose={() => { setNewKey(false); keys.reload(); }} />}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex gap-2"><dt className="text-ink-500 w-36 shrink-0">{k}</dt><dd className="text-ink-200">{v}</dd></div>;
}

const PRESETS: Record<string, string[]> = {
  "Log forwarder (ingest only)": ["event:ingest"],
  "Read-only reporting": ["incident:read", "alert:read", "report:read"],
  "Ticketing sync": ["incident:read", "incident:write", "alert:read"],
};

function NewKeyModal({ permissions, onClose }: { permissions: string[]; onClose: () => void }) {
  const action = useAction();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["event:ingest"]);
  const [days, setDays] = useState(90);
  const [created, setCreated] = useState<string | null>(null);
  const grantable = permissions.includes("*") ? Array.from(new Set(Object.values(PRESETS).flat())).sort() : [...permissions].sort();

  const create = async () => {
    await action.run(async () => {
      const res = await api.post<{ api_key: string }>("/auth/api-keys", { name, scopes, expires_in_days: days });
      setCreated(res.api_key);
    }, "Key created. Copy it now — it is shown only once and stored only as a hash.");
  };

  return (
    <Modal open onClose={onClose} title="New API key" wide>
      <ResultBanner result={action.result} />
      {created ? (
        <div>
          <div className="flex items-center gap-2 rounded-lg bg-navy-900 border border-cyan/30 p-3 font-mono text-xs break-all">
            <KeyRound className="w-4 h-4 text-cyan shrink-0" />{created}
            <button className="btn-ghost !px-2 !py-1 ml-auto shrink-0" onClick={() => navigator.clipboard?.writeText(created)} title="Copy"><Copy className="w-3.5 h-3.5" /></button>
          </div>
          <p className="text-xs text-ink-400 mt-2">Send it as the <code>X-API-Key</code> header. It acts only inside this tenant with exactly these scopes.</p>
          <div className="flex justify-end mt-3"><button className="btn-primary" onClick={onClose}>Done</button></div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Splunk HEC forwarder" /></Field>
            <Field label="Expires in (days)" hint="1–365"><input className="input" type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value))} /></Field>
          </div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(PRESETS).map(([label, s]) => <button key={label} className="btn-ghost !py-1 !text-xs" onClick={() => setScopes(s)}>{label}</button>)}
          </div>
          <Field label="Scopes" hint="You can only grant permissions you hold here.">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-1 max-h-48 overflow-y-auto border border-white/5 rounded-lg p-2">
              {grantable.map((p) => (
                <label key={p} className="flex items-center gap-1.5 text-xs">
                  <input type="checkbox" checked={scopes.includes(p)} onChange={(e) => setScopes(e.target.checked ? [...scopes, p] : scopes.filter((x) => x !== p))} />
                  <span className="font-mono">{p}</span>
                </label>
              ))}
            </div>
          </Field>
          <div className="flex justify-end gap-2">
            <button className="btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn-primary" onClick={create} disabled={action.busy || !name || !scopes.length}>Create key</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
