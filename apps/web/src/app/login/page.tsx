"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck, Loader2 } from "lucide-react";
import { useApp } from "@/lib/store";

const DEMO_ACCOUNTS = [
  ["admin@astrasoc.io", "Super Admin"],
  ["manager@acme.io", "SOC Manager"],
  ["commander@acme.io", "Incident Commander"],
  ["t1@acme.io", "Tier-1 Analyst"],
  ["auditor@acme.io", "Auditor"],
  ["exec@acme.io", "Read-only Exec"],
];

export default function LoginPage() {
  const { login } = useApp();
  const router = useRouter();
  const [email, setEmail] = useState("manager@acme.io");
  const [password, setPassword] = useState("Demo!Pass123");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.replace("/dashboard");
    } catch (err: any) {
      setError(err?.message || "Login failed");
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
          <p className="text-xs text-ink-400 tracking-wide uppercase">
            Autonomous Security Operations & Cognitive Response
          </p>
        </div>

        <form onSubmit={submit} className="panel p-6 space-y-4">
          <div>
            <label className="label block mb-1">Email</label>
            <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          </div>
          <div>
            <label className="label block mb-1">Password</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && <div className="text-sm text-crit bg-crit/10 border border-crit/30 rounded-lg px-3 py-2">{error}</div>}
          <button className="btn-primary w-full" disabled={busy}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Sign in"}
          </button>
        </form>

        <div className="panel p-4 mt-4">
          <div className="label mb-2">Demo accounts · password <span className="font-mono text-ink-200">Demo!Pass123</span></div>
          <div className="grid grid-cols-2 gap-1.5">
            {DEMO_ACCOUNTS.map(([em, role]) => (
              <button
                key={em}
                onClick={() => { setEmail(em); setPassword("Demo!Pass123"); }}
                className="text-left text-xs rounded-lg border border-white/5 px-2.5 py-1.5 hover:border-cyan/30 hover:bg-cyan/5 transition-colors"
              >
                <div className="text-ink-200 font-medium">{role}</div>
                <div className="text-ink-500 truncate">{em}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
