"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck, Loader2 } from "lucide-react";
import { useApp } from "@/lib/store";

const DEMO_PASSWORD = "Demo!Pass123";

// Grouped the way an MSSP is organised: provider staff, a co-managed
// enterprise customer's own team, and other customers.
const DEMO_ACCOUNTS: { group: string; accounts: [string, string][] }[] = [
  {
    group: "MSSP (provider)",
    accounts: [
      ["admin@astrasoc.io", "Platform Admin"],
      ["soc@astrasoc.io", "MSSP SOC Manager"],
      ["analyst@astrasoc.io", "MSSP Analyst (granted)"],
      ["accounts@astrasoc.io", "Account Manager"],
      ["ops@northwind.io", "Reseller Admin"],
    ],
  },
  {
    group: "Acme Corp (co-managed customer)",
    accounts: [
      ["ciso@acme.io", "Customer Admin (CISO)"],
      ["manager@acme.io", "SOC Manager"],
      ["commander@acme.io", "Incident Commander"],
      ["t1@acme.io", "Tier-1 Analyst"],
      ["approver@acme.io", "Customer Approver"],
      ["auditor@acme.io", "Auditor"],
    ],
  },
  {
    group: "Other customers",
    accounts: [
      ["admin@globex.io", "Globex Admin (EU)"],
      ["viewer@initech.io", "Initech Viewer"],
      ["admin@contoso.io", "Contoso Admin (via reseller)"],
    ],
  },
];

export default function LoginPage() {
  const { login, me } = useApp();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);

  useEffect(() => {
    // Only advertise demo accounts when the backend actually seeded them.
    fetch("/api/v1/auth/login-options", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { demo_accounts: false }))
      .then((o) => setDemo(!!o.demo_accounts))
      .catch(() => setDemo(false));
  }, []);

  useEffect(() => {
    if (me) router.replace(me.tenant_kind === "customer" ? "/dashboard" : "/mssp");
  }, [me, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err: any) {
      setError(err?.status === 401 ? "Invalid email or password, or the account is locked." : err?.message || "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative min-h-screen flex items-center justify-center p-4 overflow-hidden">
      <div className="absolute inset-0 bg-radar opacity-60 pointer-events-none" />
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan/60 to-transparent" />
      <div className="relative w-full max-w-md">
        <div className="flex flex-col items-center mb-6">
          <div className="relative mb-3">
            <div className="absolute inset-0 rounded-2xl bg-cyan/20 blur-xl" />
            <div className="relative w-14 h-14 rounded-2xl bg-navy-800 border border-cyan/40 flex items-center justify-center shadow-glow">
              <ShieldCheck className="w-7 h-7 text-cyan" />
            </div>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-ink-100">ASTRASOC</h1>
          <p className="text-xs text-ink-400 tracking-wide uppercase">Managed Security Operations Platform</p>
        </div>

        <form onSubmit={submit} className="panel p-6 space-y-4">
          <div>
            <label className="label block mb-1" htmlFor="email">Email</label>
            <input id="email" className="input" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          </div>
          <div>
            <label className="label block mb-1" htmlFor="password">Password</label>
            <input id="password" className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {error && <div role="alert" className="text-sm text-crit bg-crit/10 border border-crit/30 rounded-lg px-3 py-2">{error}</div>}
          <button className="btn-primary w-full" disabled={busy}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Sign in"}
          </button>
        </form>

        {demo && (
          <div className="panel p-4 mt-4">
            <div className="label mb-1">Demo environment · simulated data</div>
            <div className="text-[11px] text-ink-500 mb-3">All accounts use <span className="font-mono text-ink-200">{DEMO_PASSWORD}</span>. Never expose a demo deployment publicly.</div>
            <div className="space-y-3">
              {DEMO_ACCOUNTS.map((g) => (
                <div key={g.group}>
                  <div className="text-[10px] uppercase tracking-wider text-ink-500 mb-1">{g.group}</div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {g.accounts.map(([em, role]) => (
                      <button
                        key={em}
                        type="button"
                        onClick={() => { setEmail(em); setPassword(DEMO_PASSWORD); }}
                        className="text-left text-xs rounded-lg border border-white/5 px-2.5 py-1.5 hover:border-cyan/30 hover:bg-cyan/5 transition-colors"
                      >
                        <div className="text-ink-200 font-medium">{role}</div>
                        <div className="text-ink-500 truncate">{em}</div>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
