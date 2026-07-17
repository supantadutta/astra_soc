"use client";

import { useState } from "react";
import { Play, ShieldCheck, AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, PageHeader, Panel } from "@/components/ui";

const LANGS = ["spl", "kql", "logscale", "es", "sql", "sigma"];
const TEMPLATES: Record<string, string> = {
  spl: 'search host="FIN-WKS-014" | table _time, process, cmdline',
  kql: 'SigninLogs | where UserPrincipalName == "m.okafor@acme.io"',
  logscale: 'host="ENG-LT-233" | groupBy(dest_domain)',
  es: '{ "query": { "match": { "host_name": "SRV-DB-02" } } }',
  sql: "SELECT * FROM events WHERE severity='high'",
  sigma: "title: Test\ndetection:\n  selection:\n    activity: 'vssadmin'",
};

export default function QueryPage() {
  const [lang, setLang] = useState("spl");
  const [query, setQuery] = useState(TEMPLATES.spl);
  const [validation, setValidation] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  async function validate() {
    setValidation(await api.post<any>("/query/validate", { query, language: lang }));
  }
  async function run() {
    setErr(null); setResult(null);
    try { setResult(await api.post<any>("/query/execute", { query, language: lang, limit: 100 })); }
    catch (e: any) { setErr(e.message || "Rejected"); }
  }

  return (
    <div>
      <PageHeader title="Query Workbench" subtitle="Read-only, validated queries · destructive commands are rejected" />
      <Panel className="mb-4">
        <div className="flex gap-2 mb-3">
          {LANGS.map((l) => (
            <button key={l} onClick={() => { setLang(l); setQuery(TEMPLATES[l]); }} className={`btn-ghost !text-xs ${lang === l ? "!text-cyan !border-cyan/40" : ""}`}>{l.toUpperCase()}</button>
          ))}
        </div>
        <textarea className="input font-mono h-32" value={query} onChange={(e) => setQuery(e.target.value)} />
        <div className="flex items-center gap-2 mt-3">
          <button className="btn-ghost" onClick={validate}><ShieldCheck className="w-4 h-4" /> Validate</button>
          <button className="btn-primary" onClick={run}><Play className="w-4 h-4" /> Run</button>
          {validation && (
            <span className={`text-xs flex items-center gap-1 ${validation.read_only ? "text-teal" : "text-crit"}`}>
              {validation.read_only ? <><ShieldCheck className="w-3.5 h-3.5" /> read-only OK</> : <><AlertTriangle className="w-3.5 h-3.5" /> {validation.reason}</>}
            </span>
          )}
        </div>
      </Panel>

      {err && <div className="text-sm text-crit bg-crit/10 border border-crit/30 rounded-lg px-3 py-2 mb-3">{err}</div>}
      {result && (
        <Panel title={`Results (${result.row_count})`} actions={<Badge value="info">{result.language.toUpperCase()}</Badge>}>
          <p className="text-xs text-ink-500 mb-2">{result.note}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-left border-b border-white/5">{Object.keys(result.results[0] || { info: "" }).map((k) => <th key={k} className="label py-2 px-2">{k}</th>)}</tr></thead>
              <tbody>
                {result.results.map((row: any, i: number) => (
                  <tr key={i} className="border-b border-white/5">{Object.values(row).map((v: any, j) => <td key={j} className="py-1.5 px-2 text-ink-300 font-mono">{String(v)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}
