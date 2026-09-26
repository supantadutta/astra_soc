"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2, ShieldCheck, Smartphone } from "lucide-react";
import { api, errorMessage, setFlash } from "@/lib/api";
import { useApp } from "@/lib/store";
import { MfaEnroll, RecoveryCodes } from "@/components/MfaEnroll";

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
  return (
    <Suspense>
      <LoginScreen />
    </Suspense>
  );
}

type Step =
  | { kind: "password" }
  | { kind: "mfa"; token: string; recovery: boolean }
  | { kind: "enroll"; token: string }
  | { kind: "codes"; codes: string[] };

function LoginScreen() {
  const { login, reloadSession, me } = useApp();
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<Step>({ kind: "password" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const notice = params.get("reason") === "mfa_required"
    ? "Your organization now requires multi-factor authentication. Sign in to set it up."
    : null;

  useEffect(() => {
    // Only advertise demo accounts when the backend actually seeded them.
    fetch("/api/v1/auth/login-options", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { demo_accounts: false }))
      .then((o) => setDemo(!!o.demo_accounts))
      .catch(() => setDemo(false));
  }, []);

  useEffect(() => {
    if (me && step.kind !== "codes") router.replace(me.tenant_kind === "customer" ? "/dashboard" : "/mssp");
  }, [me, router, step.kind]);

  async function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await login(email, password);
      if (res.status === "mfa") setStep({ kind: "mfa", token: res.mfaToken, recovery: false });
      if (res.status === "enroll") setStep({ kind: "enroll", token: res.enrollmentToken });
    } catch (err: any) {
      setError(err?.status === 401 ? "Invalid email or password, or the account is locked." : errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(e: React.FormEvent) {
    e.preventDefault();
    if (step.kind !== "mfa") return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<any>("/auth/login/mfa", {
        mfa_token: step.token, session: "cookie",
        ...(step.recovery ? { recovery_code: code } : { code }),
      });
      if (typeof res?.recovery_codes_remaining === "number") {
        setFlash(`Signed in with a recovery code; ${res.recovery_codes_remaining} left. `
          + "Generate a new set in My Account if you are running low.");
      }
      await reloadSession();
    } catch (err: any) {
      setError(err?.status === 401 ? "That code is not valid (or the sign-in expired; start again)." : errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const back = () => { setStep({ kind: "password" }); setCode(""); setError(null); };

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

        {notice && step.kind === "password" && (
          <div role="status" className="mb-3 text-sm text-amber bg-amber/10 border border-amber/30 rounded-lg px-3 py-2">{notice}</div>
        )}

        {step.kind === "password" && (
          <form onSubmit={submitPassword} className="panel p-6 space-y-4">
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
        )}

        {step.kind === "mfa" && (
          <form onSubmit={submitCode} className="panel p-6 space-y-4">
            <div className="flex items-center gap-2 text-ink-100 font-medium"><Smartphone className="w-4 h-4 text-cyan" /> Two-step verification</div>
            <div>
              <label className="label block mb-1" htmlFor="mfa-code">
                {step.recovery ? "Recovery code" : "6-digit code from your authenticator app"}
              </label>
              <input id="mfa-code" className="input font-mono tracking-[0.2em] text-center text-lg" autoFocus required
                inputMode={step.recovery ? "text" : "numeric"} autoComplete="one-time-code"
                maxLength={step.recovery ? 16 : 6} value={code}
                onChange={(e) => setCode(step.recovery ? e.target.value : e.target.value.replace(/\D/g, ""))} />
            </div>
            {error && <div role="alert" className="text-sm text-crit bg-crit/10 border border-crit/30 rounded-lg px-3 py-2">{error}</div>}
            <button className="btn-primary w-full" disabled={busy || (!step.recovery && code.length !== 6)}>
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Verify"}
            </button>
            <div className="flex justify-between text-xs">
              <button type="button" className="text-ink-400 hover:text-cyan flex items-center gap-1" onClick={back}><ArrowLeft className="w-3 h-3" /> Back</button>
              <button type="button" className="text-ink-400 hover:text-cyan" onClick={() => { setStep({ ...step, recovery: !step.recovery }); setCode(""); }}>
                {step.recovery ? "Use authenticator code" : "Use a recovery code"}
              </button>
            </div>
          </form>
        )}

        {step.kind === "enroll" && (
          <div className="panel p-6 space-y-4">
            <div className="text-ink-100 font-medium flex items-center gap-2"><ShieldCheck className="w-4 h-4 text-cyan" /> Set up two-step verification</div>
            <p className="text-sm text-ink-400">Your organization requires multi-factor authentication before you can continue.</p>
            <MfaEnroll enrollmentToken={step.token} onEnrolled={(codes) => setStep({ kind: "codes", codes })} />
            <button type="button" className="text-xs text-ink-400 hover:text-cyan flex items-center gap-1" onClick={back}><ArrowLeft className="w-3 h-3" /> Back</button>
          </div>
        )}

        {step.kind === "codes" && (
          <div className="panel p-6">
            <RecoveryCodes codes={step.codes} doneLabel="Continue"
              onDone={() => { setStep({ kind: "password" }); reloadSession(); }} />
          </div>
        )}

        {demo && step.kind === "password" && (
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
