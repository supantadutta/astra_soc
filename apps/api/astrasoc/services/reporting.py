"""Report generation and export.

Reports are structured (sections with fields) and always separate CONFIRMED
FACTS from AI INFERENCES, citing evidence IDs. Export supports JSON, CSV,
printable HTML and a dependency-free built-in PDF writer (documented as
lightweight — not a full typesetting engine).
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AgentRun,
    Evidence,
    Hypothesis,
    Incident,
    ModelProvider,
    Report,
    ResponseAction,
    TimelineEntry,
)
from ..models.enums import EvidenceKind


def generate_report(db: Session, tenant_id: uuid.UUID, report_type: str, scope: str,
                    *, incident_id: uuid.UUID | None = None,
                    generated_by: uuid.UUID | None = None) -> Report:
    builders = {
        "incident": _incident_report, "executive_summary": _executive_summary,
        "technical_investigation": _technical_report, "root_cause": _root_cause,
        "response_action": _response_report, "timeline": _timeline_report,
        "attack_coverage": _attack_coverage, "llm_usage": _llm_usage,
        "automation_performance": _automation_report, "integration_health": _integration_health,
        "analyst_performance": _analyst_performance, "compliance_audit": _compliance_report,
    }
    builder = builders.get(report_type, _executive_summary)
    title, summary, content = builder(db, tenant_id, scope, incident_id)
    report = Report(
        tenant_id=tenant_id, report_type=report_type, title=title, incident_id=incident_id,
        data_scope=scope, generated_by=generated_by, format="structured",
        summary=summary, content=content,
    )
    db.add(report)
    db.flush()
    return report


def _incident_ctx(db, tenant_id, scope, incident_id):
    inc = db.get(Incident, incident_id) if incident_id else None
    if not inc:
        return None, [], [], []
    facts = db.execute(select(Evidence).where(
        Evidence.incident_id == inc.id,
        Evidence.kind == EvidenceKind.CONFIRMED_FACT.value)).scalars().all()
    inferences = db.execute(select(Evidence).where(
        Evidence.incident_id == inc.id,
        Evidence.kind == EvidenceKind.MODEL_INFERENCE.value)).scalars().all()
    hyps = db.execute(select(Hypothesis).where(Hypothesis.incident_id == inc.id)).scalars().all()
    return inc, facts, inferences, hyps


def _fact_fields(facts):
    return {f"fact_{i+1}": f"{e.title} — {e.content[:200]} [evidence:{e.id}]"
            for i, e in enumerate(facts)}


def _inference_fields(inferences):
    return {f"inference_{i+1}": f"(AI) {e.title} — confidence {e.confidence} [evidence:{e.id}]"
            for i, e in enumerate(inferences)}


def _incident_report(db, tenant_id, scope, incident_id):
    inc, facts, inferences, hyps = _incident_ctx(db, tenant_id, scope, incident_id)
    if not inc:
        return "Incident Report", "No incident specified.", {"sections": []}
    primary = next((h for h in hyps if h.is_primary), None)
    sections = [
        {"title": "Overview", "fields": {
            "incident": inc.key, "title": inc.title, "severity": inc.severity,
            "status": inc.status, "confidence": inc.confidence, "business_risk": inc.business_risk,
            "mode_scope": scope}},
        {"title": "Confirmed Facts", "fields": _fact_fields(facts)},
        {"title": "AI Inferences (not confirmed)", "fields": _inference_fields(inferences)},
        {"title": "Primary Hypothesis", "fields": {
            "statement": primary.statement if primary else "n/a",
            "confidence": primary.confidence if primary else 0,
            "missing_evidence": ", ".join(primary.missing_evidence) if primary else ""}},
        {"title": "ATT&CK", "fields": {"tactics": ", ".join(inc.attack_tactics or []),
                                       "techniques": ", ".join(inc.attack_techniques or [])}},
    ]
    return (f"Incident Report — {inc.key}", inc.summary,
            {"sections": sections, "disclaimer": _DISCLAIMER, "simulated": scope == "DEMO"})


def _executive_summary(db, tenant_id, scope, incident_id):
    if incident_id:
        inc, facts, inferences, _ = _incident_ctx(db, tenant_id, scope, incident_id)
        if inc:
            return (f"Executive Summary — {inc.key}",
                    f"{inc.severity.upper()} incident '{inc.title}'. "
                    f"{len(facts)} confirmed fact(s), business risk {inc.business_risk}/100.",
                    {"sections": [{"title": "Summary", "fields": {
                        "headline": inc.title, "severity": inc.severity,
                        "business_risk": inc.business_risk, "status": inc.status,
                        "confirmed_facts": len(facts), "recommendation":
                        "Contain and continue investigation." }}],
                     "disclaimer": _DISCLAIMER})
    open_inc = db.execute(select(func.count()).select_from(Incident).where(
        Incident.tenant_id == tenant_id, Incident.data_scope == scope)).scalar() or 0
    return ("Executive Summary — SOC Posture",
            f"{open_inc} incident(s) in scope {scope}.",
            {"sections": [{"title": "Posture", "fields": {"incidents": open_inc, "scope": scope}}],
             "disclaimer": _DISCLAIMER})


def _technical_report(db, tenant_id, scope, incident_id):
    inc, facts, inferences, hyps = _incident_ctx(db, tenant_id, scope, incident_id)
    if not inc:
        return "Technical Investigation", "No incident specified.", {"sections": []}
    tl = db.execute(select(TimelineEntry).where(TimelineEntry.incident_id == inc.id)
                    .order_by(TimelineEntry.occurred_at)).scalars().all()
    runs = db.execute(select(AgentRun).where(AgentRun.incident_id == inc.id)).scalars().all()
    sections = [
        {"title": "Technical Facts", "fields": _fact_fields(facts)},
        {"title": "Timeline", "fields": {f"t{i+1}": f"{e.occurred_at.isoformat()} — {e.title}"
                                         for i, e in enumerate(tl)}},
        {"title": "Agent Analysis", "fields": {f"agent_{i+1}":
            f"{r.agent_key}: {r.status} ({'sim' if r.simulated else r.provider_used})"
            for i, r in enumerate(runs)}},
        {"title": "Alternative Hypotheses", "fields": {
            f"alt_{i+1}": f"{h.statement} (conf {h.confidence})"
            for i, h in enumerate(h for h in hyps if not h.is_primary)}},
    ]
    return (f"Technical Investigation — {inc.key}", inc.summary,
            {"sections": sections, "disclaimer": _DISCLAIMER})


def _root_cause(db, tenant_id, scope, incident_id):
    inc, facts, _, hyps = _incident_ctx(db, tenant_id, scope, incident_id)
    if not inc:
        return "Root Cause Analysis", "No incident specified.", {"sections": []}
    primary = next((h for h in hyps if h.is_primary), None)
    return (f"Root Cause Analysis — {inc.key}",
            primary.statement if primary else "Root cause not yet established.",
            {"sections": [
                {"title": "Root Cause (hypothesis)", "fields": {
                    "statement": primary.statement if primary else "n/a",
                    "confidence": primary.confidence if primary else 0,
                    "supporting_facts": len(facts)}},
                {"title": "Missing Evidence", "fields": {
                    f"gap_{i+1}": g for i, g in enumerate(primary.missing_evidence if primary else [])}},
            ], "disclaimer": _DISCLAIMER})


def _response_report(db, tenant_id, scope, incident_id):
    q = select(ResponseAction).where(ResponseAction.tenant_id == tenant_id,
                                     ResponseAction.data_scope == scope)
    if incident_id:
        q = q.where(ResponseAction.incident_id == incident_id)
    actions = db.execute(q).scalars().all()
    return ("Response Action Report", f"{len(actions)} action(s).",
            {"sections": [{"title": "Actions", "fields": {
                f"a{i+1}": f"{a.action_type} -> {a.status} "
                          f"({'simulated' if a.simulated else 'live'})"
                for i, a in enumerate(actions)}}], "disclaimer": _DISCLAIMER})


def _timeline_report(db, tenant_id, scope, incident_id):
    if not incident_id:
        return "Timeline Report", "No incident specified.", {"sections": []}
    tl = db.execute(select(TimelineEntry).where(TimelineEntry.incident_id == incident_id)
                    .order_by(TimelineEntry.occurred_at)).scalars().all()
    return ("Timeline Report", f"{len(tl)} events.",
            {"sections": [{"title": "Timeline", "fields": {
                f"t{i+1}": f"{e.occurred_at.isoformat()} [{e.category}] {e.title}"
                for i, e in enumerate(tl)}}]})


def _attack_coverage(db, tenant_id, scope, incident_id):
    incs = db.execute(select(Incident).where(Incident.tenant_id == tenant_id,
                                             Incident.data_scope == scope)).scalars().all()
    counter: dict[str, int] = {}
    for inc in incs:
        for t in inc.attack_techniques or []:
            counter[t] = counter.get(t, 0) + 1
    return ("MITRE ATT&CK Coverage Report", f"{len(counter)} techniques observed.",
            {"sections": [{"title": "Techniques", "fields":
                          {k: v for k, v in sorted(counter.items(), key=lambda x: -x[1])}}]})


def _llm_usage(db, tenant_id, scope, incident_id):
    provs = db.execute(select(ModelProvider).where(
        ModelProvider.tenant_id == tenant_id)).scalars().all()
    return ("LLM Usage & Cost Report", f"{len(provs)} provider(s).",
            {"sections": [{"title": "Providers", "fields": {
                p.name: f"{p.total_requests} req, {p.total_tokens} tok, "
                        f"${p.total_cost_usd:.4f}, health {p.health}" for p in provs}}]})


def _automation_report(db, tenant_id, scope, incident_id):
    runs = db.execute(select(AgentRun).where(AgentRun.tenant_id == tenant_id,
                                             AgentRun.data_scope == scope)).scalars().all()
    ok = sum(1 for r in runs if r.status == "succeeded")
    return ("Automation Performance Report", f"{ok}/{len(runs)} agent runs succeeded.",
            {"sections": [{"title": "Agent Runs", "fields": {
                "total": len(runs), "succeeded": ok,
                "success_rate": round(ok / len(runs), 3) if runs else 0}}]})


def _integration_health(db, tenant_id, scope, incident_id):
    from ..models import Connector
    conns = db.execute(select(Connector).where(Connector.tenant_id == tenant_id)).scalars().all()
    return ("Integration Health Report", f"{len(conns)} connectors.",
            {"sections": [{"title": "Connectors", "fields": {
                c.name: f"enabled={c.enabled} write={c.can_write} mock={c.use_mock}"
                for c in conns}}]})


def _analyst_performance(db, tenant_id, scope, incident_id):
    from ..models import User
    users = db.execute(select(User).where(User.tenant_id == tenant_id)).scalars().all()
    return ("Analyst Performance Report", f"{len(users)} analysts.",
            {"sections": [{"title": "Analysts", "fields": {u.full_name: u.email for u in users}}]})


def _compliance_report(db, tenant_id, scope, incident_id):
    from ..services.audit import verify_audit_chain
    chain = verify_audit_chain(db)
    return ("Compliance Audit Report",
            f"Audit chain {'verified' if chain['verified'] else 'BROKEN'} over {chain['checked']} entries.",
            {"sections": [{"title": "Audit Integrity", "fields": chain}]})


_DISCLAIMER = ("This report distinguishes CONFIRMED FACTS from AI INFERENCES. AI inferences are "
               "advisory and must be validated by an analyst before action. Evidence IDs are cited "
               "for traceability.")


# --- Exports --------------------------------------------------------------
def export_html(report: Report) -> str:
    rows = []
    for section in report.content.get("sections", []):
        rows.append(f"<h2>{section.get('title','')}</h2><table>")
        for k, v in section.get("fields", {}).items():
            rows.append(f"<tr><th>{k}</th><td>{v}</td></tr>")
        rows.append("</table>")
    banner = ("<div class='sim'>SIMULATED / DEMO DATA</div>"
              if report.data_scope == "DEMO" else "")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{report.title}</title>
<style>body{{font-family:system-ui;margin:2rem;color:#0b1220}}h1{{color:#0b5}}.sim{{background:#b45309;
color:#fff;padding:6px 10px;border-radius:6px;display:inline-block;margin-bottom:1rem}}
table{{border-collapse:collapse;margin:1rem 0;width:100%}}th,td{{border:1px solid #ccc;padding:6px 10px;
text-align:left;vertical-align:top}}th{{background:#f1f5f9;width:220px}}
.disc{{color:#555;font-size:.85rem;margin-top:2rem;border-top:1px solid #ddd;padding-top:1rem}}</style>
</head><body>{banner}<h1>{report.title}</h1><p>{report.summary}</p>{''.join(rows)}
<div class="disc">{report.content.get('disclaimer','')}</div></body></html>"""


def export_pdf_like(report: Report) -> bytes:
    """Minimal, dependency-free PDF with the report text.

    This is a lightweight built-in writer (single Helvetica text stream), not a
    full typesetting engine. It produces a valid, openable PDF; for richly
    formatted PDFs, wire a real renderer in production.
    """
    lines = [report.title, "", report.summary, ""]
    for section in report.content.get("sections", []):
        lines.append(section.get("title", ""))
        for k, v in section.get("fields", {}).items():
            lines.append(f"  {k}: {v}")
        lines.append("")
    lines.append(report.content.get("disclaimer", ""))

    def esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")[:110]

    text_ops = ["BT", "/F1 11 Tf", "1 0 0 1 50 780 Tm", "13 TL"]
    for ln in lines[:60]:
        text_ops.append(f"({esc(ln)}) Tj")
        text_ops.append("T*")
    text_ops.append("ET")
    stream = "\n".join(text_ops)

    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = "%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(pdf.encode("latin-1", "replace")))
        pdf += f"{i} 0 obj\n{obj}\nendobj\n"
    xref_pos = len(pdf.encode("latin-1", "replace"))
    pdf += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n"
    pdf += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF")
    return pdf.encode("latin-1", "replace")
