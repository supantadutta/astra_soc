"use client";

import { useEffect, useState } from "react";
import { Lock, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Loading, Modal, PageHeader, Panel } from "@/components/ui";
import { titleCase } from "@/lib/ui";

export default function RBACPage() {
  const [roles, setRoles] = useState<any[]>([]);
  const [users, setUsers] = useState<any[]>([]);
  const [perms, setPerms] = useState<any[]>([]);
  const [selRole, setSelRole] = useState<any>(null);
  const [assignUser, setAssignUser] = useState<any>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      const [r, u, p] = await Promise.all([
        api.get<any>("/rbac/roles"), api.get<any>("/rbac/users"), api.get<any>("/rbac/permissions"),
      ]);
      setRoles(r.items); setUsers(u.items); setPerms(p.permissions);
    } catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  if (err) return <div className="text-crit py-16 text-center">Access denied: {err}. RBAC administration requires rbac:manage.</div>;

  return (
    <div>
      <PageHeader title="RBAC" subtitle={`${roles.length} roles · ${users.length} users · ${perms.length} permissions — all enforced server-side`} />
      {toast && <div className="mb-3 text-sm text-teal bg-teal/10 border border-teal/30 rounded-lg px-3 py-2">{toast}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Panel title="Roles & Permission Matrix">
          <div className="space-y-1.5 max-h-[560px] overflow-y-auto">
            {roles.map((r) => (
              <button key={r.id} onClick={() => setSelRole(r)} className="w-full text-left rounded-lg border border-white/5 px-3 py-2 hover:border-cyan/30 transition-colors">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-sm text-ink-100"><Lock className="w-3.5 h-3.5 text-cyan" /> {titleCase(r.name)}</span>
                  <span className="text-xs text-ink-500">{r.permissions?.includes("*") ? "ALL" : r.permissions?.length} perms</span>
                </div>
                <p className="text-xs text-ink-500">{r.description}</p>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title="Users & Assignments">
          <div className="space-y-1.5 max-h-[560px] overflow-y-auto">
            {users.map((u) => (
              <div key={u.id} className="rounded-lg border border-white/5 px-3 py-2">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm text-ink-100">{u.full_name}</div>
                    <div className="text-xs text-ink-500">{u.email}</div>
                  </div>
                  <button className="btn-ghost !py-1 !text-xs" onClick={() => setAssignUser(u)}><Plus className="w-3 h-3" /> Assign role</button>
                </div>
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {u.roles?.map((r: any) => (
                    <span key={r.role} className="chip text-ink-300 border-white/10 bg-white/5">
                      {titleCase(r.role)}{r.expires_at ? " ⏱" : ""}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Modal open={!!selRole} onClose={() => setSelRole(null)} title={selRole ? titleCase(selRole.name) : ""} wide>
        {selRole && (
          <div>
            <p className="text-sm text-ink-400 mb-3">{selRole.description}</p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-1">
              {(selRole.permissions?.includes("*") ? perms.map((p: any) => p.key) : selRole.permissions || []).map((p: string) => (
                <span key={p} className="chip text-teal border-teal/30 bg-teal/5 font-mono text-[10px]">{p}</span>
              ))}
            </div>
          </div>
        )}
      </Modal>

      <Modal open={!!assignUser} onClose={() => setAssignUser(null)} title={`Assign role to ${assignUser?.full_name || ""}`}>
        {assignUser && <AssignForm user={assignUser} roles={roles} onDone={() => { setAssignUser(null); load(); setToast("Role assigned."); }} />}
      </Modal>
    </div>
  );
}

function AssignForm({ user, roles, onDone }: any) {
  const [role, setRole] = useState(roles[0]?.name || "");
  const [temp, setTemp] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    try {
      await api.post(`/rbac/users/${user.id}/roles`, { role, temporary_minutes: temp || undefined });
      onDone();
    } catch (e: any) { setErr(e.message); }
  }
  return (
    <div className="space-y-3">
      <select className="input" value={role} onChange={(e) => setRole(e.target.value)}>
        {roles.map((r: any) => <option key={r.id} value={r.name}>{titleCase(r.name)}</option>)}
      </select>
      <div>
        <label className="label block mb-1">Temporary elevation (minutes, 0 = permanent)</label>
        <input className="input" type="number" min={0} value={temp} onChange={(e) => setTemp(Number(e.target.value))} />
      </div>
      {err && <div className="text-crit text-sm">{err}</div>}
      <button className="btn-primary w-full" onClick={save}>Assign</button>
    </div>
  );
}
