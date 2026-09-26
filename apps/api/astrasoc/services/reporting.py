"""Report generation and export.

Reports are structured (sections with fields) and always separate CONFIRMED
FACTS from AI INFERENCES, citing evidence IDs. Every query here is filtered
by tenant AND data scope — a report can never include another tenant's data,
whatever incident id the caller supplies (it is validated first).

Export supports JSON, CSV, HTML (all values escaped) and a dependency-free
PDF writer (documented as lightweight — not a full typesetting engine).
"""
from __future__ import annotations

import html
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AgentRun,
    Alert,
    Connector,
    DetectionRule,
    Evidence,
    Hypothesis,
    Incident,
    ModelProvider,
    Report,
    ResponseAction,
    Tenant,
    TimelineEntry,
    User,
)
from ..models.enums import EvidenceKind


class ReportError(ValueError):
    pass


REPORT_TYPES = [
    "incident", "executive_summary", "technical_investigation", "root_cause",
    "response_action", "timeline", "attack_coverage", "analyst_performance",
    "automation_performance", "llm_usage", "integration_health", "compliance_audit",
    "service_report",
]
INCIDENT_REPORTS = {"incident", "technical_investigation", "root_cause", "timeline"}


def generate_report(db: Session, tenant_id: uuid.UUID, report_type: str, scope: str,
                    *, incident_id: uuid.UUID | None = None,
                    generated_by: uuid.UUID | None = None,
                    parameters: dict | None = None) -> Report:
    if report_type not in REPORT_TYPES:
        raise ReportError(f"Unknown report type '{report_type}'.")
    if incident_id is not None:
        inc = db.get(Incident, incident_id)
        if inc is None or inc.tenant_id != tenant_id or inc.data_scope != scope:
            raise ReportError("Incident not found.")
    elif report_type in INCIDENT_REPORTS:
        raise ReportError(f"Report type '{report_type}' requires an incident_id.")
    builder = _BUILDERS[report_type]
    title, summary, content = builder(db, tenant_id, scope, incident_id, parameters or {})
    content.setdefault("disclaimer", _DISCLAIMER)
    content["simulated"] = scope == "DEMO"
    report = Report(
        tenant_id=tenant_id, report_type=report_type, title=title, incident_id=incident_id,
        data_scope=scope, generated_by=generated_by, format="structured",
        summary=summary, content=content, parameters=parameters or {},
    )
    db.add(report)
    db.flush()
    from .metering import record

    record(db, tenant_id, "reports")
    return report


def _incident_ctx(db, tenant_id, scope, incident_id):
    inc = db.get(Incident, incident_id) if incident_id else None
    if not inc or inc.tenant_id != tenant_id or inc.data_scope != scope:
        return None, [], [], []

    def ev(kind):
        return db.execute(select(Evidence).where(
            Evidence.tenant_id == tenant_id, Evidence.data_scope == scope,
            Evidence.incident_id == inc.id, Evidence.kind == kind)).scalars().all()

    hyps = db.execute(select(Hypothesis).where(
        Hypothesis.tenant_id == tenant_id, Hypothesis.data_scope == scope,
        Hypothesis.incident_id == inc.id)).scalars().all()
    return inc, ev(EvidenceKind.CONFIRMED_FACT.value), ev(EvidenceKind.MODEL_INFERENCE.value), hyps


def _timeline(db, tenant_id, scope, incident_id):
    return db.execute(select(TimelineEntry).where(
        TimelineEntry.tenant_id == tenant_id, TimelineEntry.data_scope == scope,
        TimelineEntry.incident_id == incident_id).order_by(TimelineEntry.occurred_at)).scalars().all()


def _fact_fields(facts):
    return {f"fact_{i+1}": f"{e.title} — {e.content[:200]} [evidence:{e.id}]"
            for i, e in enumerate(facts)}


def _inference_fields(inferences):
    return {f"inference_{i+1}": f"(AI) {e.title} — confidence {e.confidence} [evidence:{e.id}]"
            for i, e in enumerate(inferences)}


def _incident_report(db, tenant_id, scope, incident_id, params):
    inc, facts, inferences, hyps = _incident_ctx(db, tenant_id, scope, incident_id)
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
    return f"Incident Report — {inc.key}", inc.summary, {"sections": sections}


def _executive_summary(db, tenant_id, scope, incident_id, params):
    if incident_id:
        inc, facts, _, _ = _incident_ctx(db, tenant_id, scope, incident_id)
        return (f"Executive Summary — {inc.key}",
                f"{inc.severity.upper()} incident '{inc.title}'. "
                f"{len(facts)} confirmed fact(s), business risk {inc.business_risk}/100.",
                {"sections": [{"title": "Summary", "fields": {
                    "headline": inc.title, "severity": inc.severity,
                    "business_risk": inc.business_risk, "status": inc.status,
                    "confirmed_facts": len(facts)}}]})
    rows = db.execute(select(Incident.severity, Incident.status, func.count()).where(
        Incident.tenant_id == tenant_id, Incident.data_scope == scope)
        .group_by(Incident.severity, Incident.status)).all()
    total = sum(r[2] for r in rows)
    open_ = sum(r[2] for r in rows if r[1] not in ("resolved", "closed", "false_positive"))
    return ("Executive Summary — SOC Posture", f"{total} incident(s), {open_} open, scope {scope}.",
            {"sections": [{"title": "Posture", "fields": {
                "incidents_total": total, "incidents_open": open_, "scope": scope,
                **{f"{s}/{st}": n for s, st, n in rows}}}]})


def _technical_report(db, tenant_id, scope, incident_id, params):
    inc, facts, _, hyps = _incident_ctx(db, tenant_id, scope, incident_id)
    runs = db.execute(select(AgentRun).where(
        AgentRun.tenant_id == tenant_id, AgentRun.incident_id == inc.id)).scalars().all()
    sections = [
        {"title": "Technical Facts", "fields": _fact_fields(facts)},
        {"title": "Timeline", "fields": {f"t{i+1}": f"{e.occurred_at.isoformat()} — {e.title}"
                                         for i, e in enumerate(_timeline(db, tenant_id, scope, inc.id))}},
        {"title": "Agent Analysis", "fields": {
            f"agent_{i+1}": f"{r.agent_key}: {r.status} ({'sim' if r.simulated else r.provider_used})"
            for i, r in enumerate(runs)}},
        {"title": "Alternative Hypotheses", "fields": {
            f"alt_{i+1}": f"{h.statement} (conf {h.confidence})"
            for i, h in enumerate(h for h in hyps if not h.is_primary)}},
    ]
    return f"Technical Investigation — {inc.key}", inc.summary, {"sections": sections}


def _root_cause(db, tenant_id, scope, incident_id, params):
    inc, facts, _, hyps = _incident_ctx(db, tenant_id, scope, incident_id)
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
            ]})


def _response_report(db, tenant_id, scope, incident_id, params):
    q = select(ResponseAction).where(ResponseAction.tenant_id == tenant_id,
                                     ResponseAction.data_scope == scope)
    if incident_id:
        q = q.where(ResponseAction.incident_id == incident_id)
    actions = db.execute(q).scalars().all()
    return ("Response Action Report", f"{len(actions)} action(s).",
            {"sections": [{"title": "Actions", "fields": {
                f"a{i+1}": f"{a.action_type} -> {a.status} ({'simulated' if a.simulated else 'live'})"
                for i, a in enumerate(actions)}}]})


def _timeline_report(db, tenant_id, scope, incident_id, params):
    tl = _timeline(db, tenant_id, scope, incident_id)
    return ("Timeline Report", f"{len(tl)} events.",
            {"sections": [{"title": "Timeline", "fields": {
                f"t{i+1}": f"{e.occurred_at.isoformat()} [{e.category}] {e.title}"
                for i, e in enumerate(tl)}}]})


def _attack_coverage(db, tenant_id, scope, incident_id, params):
    counter: dict[str, int] = {}
    for inc in db.execute(select(Incident).where(Incident.tenant_id == tenant_id,
                                                 Incident.data_scope == scope)).scalars():
        for t in inc.attack_techniques or []:
            counter[t] = counter.get(t, 0) + 1
    rules = db.execute(select(DetectionRule).where(DetectionRule.tenant_id == tenant_id,
                                                   DetectionRule.enabled.is_(True))).scalars().all()
    covered = sorted({t for r in rules for t in (r.attack_techniques or [])})
    return ("MITRE ATT&CK Coverage Report",
            f"{len(counter)} techniques observed; {len(covered)} covered by enabled detections.",
            {"sections": [
                {"title": "Observed techniques", "fields":
                    {k: v for k, v in sorted(counter.items(), key=lambda x: -x[1])}},
                {"title": "Detection coverage", "fields": {"techniques": ", ".join(covered)}},
            ]})


def _llm_usage(db, tenant_id, scope, incident_id, params):
    provs = db.execute(select(ModelProvider).where(ModelProvider.tenant_id == tenant_id)).scalars().all()
    return ("LLM Usage & Cost Report", f"{len(provs)} provider(s).",
            {"sections": [{"title": "Providers", "fields": {
                p.name: f"{p.total_requests} req, {p.total_tokens} tok, "
                        f"${p.total_cost_usd:.4f}, health {p.health}" for p in provs}}]})


def _automation_report(db, tenant_id, scope, incident_id, params):
    runs = db.execute(select(AgentRun).where(AgentRun.tenant_id == tenant_id,
                                             AgentRun.data_scope == scope)).scalars().all()
    ok = sum(1 for r in runs if r.status == "succeeded")
    return ("Automation Performance Report", f"{ok}/{len(runs)} agent runs succeeded.",
            {"sections": [{"title": "Agent Runs", "fields": {
                "total": len(runs), "succeeded": ok,
                "success_rate": round(ok / len(runs), 3) if runs else 0}}]})


def _integration_health(db, tenant_id, scope, incident_id, params):
    conns = db.execute(select(Connector).where(Connector.tenant_id == tenant_id)).scalars().all()
    return ("Integration Health Report", f"{len(conns)} connectors.",
            {"sections": [{"title": "Connectors", "fields": {
                c.name: f"enabled={c.enabled} write={c.can_write} mock={c.use_mock}"
                for c in conns}}]})


def _analyst_performance(db, tenant_id, scope, incident_id, params):
    users = db.execute(select(User).where(User.tenant_id == tenant_id)).scalars().all()
    owned = dict(db.execute(select(Incident.owner_id, func.count()).where(
        Incident.tenant_id == tenant_id, Incident.data_scope == scope)
        .group_by(Incident.owner_id)).all())
    return ("Analyst Performance Report", f"{len(users)} analysts.",
            {"sections": [{"title": "Incidents owned", "fields": {
                u.full_name: owned.get(u.id, 0) for u in users}}]})


def _compliance_report(db, tenant_id, scope, incident_id, params):
    from .audit import verify_audit_chain

    chain = verify_audit_chain(db)
    return ("Compliance Audit Report",
            f"Audit chain {'verified' if chain['verified'] else 'BROKEN'} over {chain['checked']} entries.",
            {"sections": [{"title": "Audit Integrity", "fields": chain}]})


def _service_report(db, tenant_id, scope, incident_id, params):
    """The monthly managed-service report an MSSP delivers to a customer."""
    from .metering import METRICS, period_of, usage_for
    from .sla import sla_report

    tenant = db.get(Tenant, tenant_id)
    period = params.get("period") or period_of()
    start = datetime.strptime(period + "-01", "%Y-%m-%d").replace(tzinfo=UTC)
    end = (start + timedelta(days=32)).replace(day=1)
    sla = sla_report(db, [tenant_id], start, end, scope=scope)[0]
    usage = usage_for(db, [tenant_id], period)[tenant_id]
    alerts = db.execute(select(func.count()).select_from(Alert).where(
        Alert.tenant_id == tenant_id, Alert.data_scope == scope,
        Alert.created_at >= start, Alert.created_at < end)).scalar() or 0
    actions = db.execute(select(ResponseAction.action_type, ResponseAction.status, func.count()).where(
        ResponseAction.tenant_id == tenant_id, ResponseAction.data_scope == scope,
        ResponseAction.created_at >= start, ResponseAction.created_at < end)
        .group_by(ResponseAction.action_type, ResponseAction.status)).all()
    techniques: dict[str, int] = {}
    for inc in db.execute(select(Incident).where(
            Incident.tenant_id == tenant_id, Incident.data_scope == scope,
            Incident.created_at >= start, Incident.created_at < end)).scalars():
        for t in inc.attack_techniques or []:
            techniques[t] = techniques.get(t, 0) + 1
    def pct(v: float | None) -> str:
        return f"{v * 100:.1f}%" if v is not None else "n/a"
    sections = [
        {"title": "Service summary", "fields": {
            "customer": tenant.name, "period": period, "service_tier": tenant.service_tier,
            "alerts_triaged": alerts, "incidents": sla["incidents"],
            "open_sla_breaches": sla["open_breaches"]}},
        {"title": "SLA performance", "fields": {
            "acknowledge_compliance": pct(sla["ack_compliance"]),
            "resolve_compliance": pct(sla["resolve_compliance"]),
            "mtta_minutes": sla["mtta_minutes"], "mttr_minutes": sla["mttr_minutes"],
            **{f"incidents_{k}": v for k, v in sla["by_severity"].items()}}},
        {"title": "Response actions", "fields": {f"{a} ({s})": n for a, s, n in actions}},
        {"title": "Top ATT&CK techniques", "fields": dict(
            sorted(techniques.items(), key=lambda x: -x[1])[:10])},
        {"title": "Service usage", "fields": {METRICS[k]: v for k, v in usage.items()}},
    ]
    return (f"Managed Security Service Report — {tenant.name} — {period}",
            f"{sla['incidents']} incidents; acknowledge SLA {pct(sla['ack_compliance'])}, "
            f"resolve SLA {pct(sla['resolve_compliance'])}.",
            {"sections": sections})


_BUILDERS = {
    "incident": _incident_report, "executive_summary": _executive_summary,
    "technical_investigation": _technical_report, "root_cause": _root_cause,
    "response_action": _response_report, "timeline": _timeline_report,
    "attack_coverage": _attack_coverage, "llm_usage": _llm_usage,
    "automation_performance": _automation_report, "integration_health": _integration_health,
    "analyst_performance": _analyst_performance, "compliance_audit": _compliance_report,
    "service_report": _service_report,
}

_DISCLAIMER = ("This report distinguishes CONFIRMED FACTS from AI INFERENCES. AI inferences are "
               "advisory and must be validated by an analyst before action. Evidence IDs are cited "
               "for traceability.")


# --- Exports --------------------------------------------------------------
def export_html(report: Report, branding: dict | None = None) -> str:
    e = html.escape
    branding = branding or {}
    color = branding.get("primary_color", "#0b5")
    if not (isinstance(color, str) and color.startswith("#") and len(color) in (4, 7)
            and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
        color = "#0b5"
    rows = []
    for section in report.content.get("sections", []):
        rows.append(f"<h2>{e(str(section.get('title', '')))}</h2><table>")
        for k, v in section.get("fields", {}).items():
            rows.append(f"<tr><th>{e(str(k))}</th><td>{e(str(v))}</td></tr>")
        rows.append("</table>")
    banner = ("<div class='sim'>SIMULATED / DEMO DATA</div>" if report.data_scope == "DEMO" else "")
    brand = e(str(branding.get("display_name", "")))
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>{e(report.title)}</title>
<style>body{{font-family:system-ui;margin:2rem;color:#0b1220}}h1{{color:{color}}}.sim{{background:#b45309;
color:#fff;padding:6px 10px;border-radius:6px;display:inline-block;margin-bottom:1rem}}
table{{border-collapse:collapse;margin:1rem 0;width:100%}}th,td{{border:1px solid #ccc;padding:6px 10px;
text-align:left;vertical-align:top}}th{{background:#f1f5f9;width:220px}}.brand{{color:#555}}
.disc{{color:#555;font-size:.85rem;margin-top:2rem;border-top:1px solid #ddd;padding-top:1rem}}</style>
</head><body>{banner}<div class="brand">{brand}</div><h1>{e(report.title)}</h1><p>{e(report.summary)}</p>
{''.join(rows)}<div class="disc">{e(str(report.content.get('disclaimer', '')))}</div></body></html>"""


def export_pdf_like(report: Report) -> bytes:
    """Minimal, dependency-free PDF (multi-page, Helvetica text)."""
    lines = [report.title, "", report.summary, ""]
    for section in report.content.get("sections", []):
        lines.append(str(section.get("title", "")))
        for k, v in section.get("fields", {}).items():
            text = f"  {k}: {v}"
            while len(text) > 100:
                lines.append(text[:100])
                text = "    " + text[100:]
            lines.append(text)
        lines.append("")
    lines.append(str(report.content.get("disclaimer", "")))
    if report.data_scope == "DEMO":
        lines.insert(0, "SIMULATED / DEMO DATA")

    def esc(s: str) -> str:
        s = s.encode("latin-1", "replace").decode("latin-1")
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    per_page = 55
    pages = [lines[i:i + per_page] for i in range(0, max(1, len(lines)), per_page)]
    objs: list[str] = ["<< /Type /Catalog /Pages 2 0 R >>", ""]  # pages dict filled later
    font_id = 3
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    for chunk in pages:
        ops = ["BT", "/F1 10 Tf", "1 0 0 1 50 790 Tm", "13 TL"]
        for ln in chunk:
            ops += [f"({esc(ln)}) Tj", "T*"]
        ops.append("ET")
        stream = "\n".join(ops)
        objs.append(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")
        content_id = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>")
        page_ids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(page_ids)} >>"
    pdf = "%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(pdf.encode("latin-1")))
        pdf += f"{i} 0 obj\n{obj}\nendobj\n"
    xref = len(pdf.encode("latin-1"))
    pdf += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
    pdf += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    pdf += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    return pdf.encode("latin-1")
