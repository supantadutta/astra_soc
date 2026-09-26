"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { Copy, Download, KeyRound, Loader2, ShieldCheck } from "lucide-react";
import { api, errorMessage } from "@/lib/api";

/**
 * Enroll an authenticator app. With `enrollmentToken` this is the first
 * sign-in of a user whose organization requires MFA (completing it also
 * signs them in); without it, the signed-in user adds MFA from My Account.
 */
export function MfaEnroll({ enrollmentToken, onEnrolled }: {
  enrollmentToken?: string;
  onEnrolled: (recoveryCodes: string[]) => void;
}) {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.post<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup",
      enrollmentToken ? { enrollment_token: enrollmentToken } : {})
      .then(async (s) => {
        if (cancelled) return;
        setSetup(s);
        setQr(await QRCode.toDataURL(s.otpauth_uri, { margin: 1, width: 200 }));
      })
      .catch((e) => setError(errorMessage(e)));
    return () => { cancelled = true; };
  }, [enrollmentToken]);

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ recovery_codes: string[] }>("/auth/mfa/enable", {
        code, ...(enrollmentToken ? { enrollment_token: enrollmentToken, session: "cookie" } : {}),
      });
      onEnrolled(res.recovery_codes);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!setup) {
    return error
      ? <div role="alert" className="text-sm text-crit">{error}</div>
      : <div className="flex items-center gap-2 text-ink-400 text-sm"><Loader2 className="w-4 h-4 animate-spin" /> Preparing…</div>;
  }
  return (
    <form onSubmit={confirm} className="space-y-4">
      <ol className="text-sm text-ink-300 space-y-1 list-decimal list-inside">
        <li>Open an authenticator app (Microsoft Authenticator, Google Authenticator, 1Password, Authy…).</li>
        <li>Scan the code, or enter the key manually.</li>
        <li>Type the 6-digit code it shows.</li>
      </ol>
      <div className="flex flex-col sm:flex-row items-center gap-4">
        {/* eslint-disable-next-line @next/next/no-img-element -- local data: URL, nothing to optimise */}
        {qr && <img src={qr} alt="Authenticator QR code" width={180} height={180} className="rounded-lg bg-white p-1" />}
        <div className="text-xs text-ink-400 break-all">
          <div className="label mb-1">Manual key</div>
          <code className="text-ink-100 text-sm tracking-wider">{setup.secret.match(/.{1,4}/g)?.join(" ")}</code>
          <div className="mt-2">Type: time-based · 6 digits · 30 seconds</div>
        </div>
      </div>
      <div>
        <label className="label block mb-1" htmlFor="mfa-enroll-code">Code from the app</label>
        <input id="mfa-enroll-code" className="input font-mono tracking-[0.3em] text-center text-lg" inputMode="numeric"
          autoComplete="one-time-code" maxLength={6} required value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} autoFocus />
      </div>
      {error && <div role="alert" className="text-sm text-crit bg-crit/10 border border-crit/30 rounded-lg px-3 py-2">{error}</div>}
      <button className="btn-primary w-full" disabled={busy || code.length !== 6}>
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <><ShieldCheck className="w-4 h-4" /> Verify and enable</>}
      </button>
    </form>
  );
}

/** Recovery codes are shown exactly once. */
export function RecoveryCodes({ codes, onDone, doneLabel = "I have saved these codes" }: {
  codes: string[];
  onDone: () => void;
  doneLabel?: string;
}) {
  const text = `ASTRASOC recovery codes (each works once)\n\n${codes.join("\n")}\n`;
  const save = () => {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "astrasoc-recovery-codes.txt";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 text-sm text-amber bg-amber/10 border border-amber/30 rounded-lg px-3 py-2">
        <KeyRound className="w-4 h-4 mt-0.5 shrink-0" />
        Save these recovery codes somewhere safe. Each one signs you in once if you lose your device.
        They will not be shown again.
      </div>
      <div className="grid grid-cols-2 gap-2 font-mono text-sm">
        {codes.map((c) => <div key={c} className="rounded-lg bg-navy-900 border border-white/10 px-3 py-1.5 text-center text-ink-100">{c}</div>)}
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-ghost" onClick={() => navigator.clipboard?.writeText(text)}><Copy className="w-4 h-4" /> Copy</button>
        <button type="button" className="btn-ghost" onClick={save}><Download className="w-4 h-4" /> Download</button>
        <button type="button" className="btn-primary ml-auto" onClick={onDone}>{doneLabel}</button>
      </div>
    </div>
  );
}
