"""Reports API: generate, list, retrieve, and export (PDF/CSV/JSON/HTML)."""
from __future__ import annotations

import csv
import io
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import Report
from ..schemas.common import serialize
from ..services import audit
from ..services.mode import current_scope
from ..services.reporting import export_html, export_pdf_like, generate_report

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

REPORT_TYPES = [
    "incident", "executive_summary", "technical_investigation", "root_cause",
    "response_action", "timeline", "attack_coverage", "analyst_performance",
    "automation_performance", "llm_usage", "integration_health", "compliance_audit",
]


@router.get("/types")
def types(principal: Principal = Depends(require_permission("report:read"))) -> dict:
    return {"types": REPORT_TYPES}


@router.get("")
def list_reports(principal: Principal = Depends(require_permission("report:read")),
                 db: Session = Depends(get_db),
                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                 report_type: str | None = None) -> dict:
    scope = current_scope(db)
    filters = [Report.report_type == report_type] if report_type else []
    return paginate(db, Report, tenant_id=principal.tenant_id, scope=scope, filters=filters,
                    sort="created_at", page=page, page_size=page_size, exclude={"content"})


@router.post("")
def create_report(payload: dict,
                  principal: Principal = Depends(require_permission("report:generate")),
                  db: Session = Depends(get_db)) -> dict:
    report_type = payload.get("report_type")
    if report_type not in REPORT_TYPES:
        raise HTTPException(422, detail="Invalid report type")
    scope = current_scope(db)
    incident_id = uuid.UUID(payload["incident_id"]) if payload.get("incident_id") else None
    report = generate_report(db, principal.tenant_id, report_type, scope,
                             incident_id=incident_id, generated_by=principal.user_id)
    audit.record(db, action="report.generated", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="report",
                 resource_id=str(report.id), data_scope=scope, detail={"type": report_type})
    db.commit()
    return serialize(report)


@router.get("/{report_id}")
def get_report(report_id: uuid.UUID,
               principal: Principal = Depends(require_permission("report:read")),
               db: Session = Depends(get_db)) -> dict:
    r = db.get(Report, report_id)
    if not r or r.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Report not found")
    return serialize(r)


@router.get("/{report_id}/export")
def export(report_id: uuid.UUID, format: str = Query("json", pattern="^(json|csv|html|pdf)$"),
           principal: Principal = Depends(require_permission("report:read")),
           db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if not r or r.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Report not found")
    if format == "json":
        return Response(content=json.dumps(serialize(r), indent=2, default=str),
                        media_type="application/json",
                        headers={"content-disposition": f"attachment; filename=report-{r.id}.json"})
    if format == "html":
        return PlainTextResponse(export_html(r), media_type="text/html")
    if format == "pdf":
        # Dependency-free printable document (PDF-like). Documented as such.
        return Response(content=export_pdf_like(r), media_type="application/pdf",
                        headers={"content-disposition": f"attachment; filename=report-{r.id}.pdf"})
    # CSV: flatten the sections.
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["section", "key", "value"])
    for section in r.content.get("sections", []):
        for k, v in section.get("fields", {}).items():
            writer.writerow([section.get("title", ""), k, v])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"content-disposition": f"attachment; filename=report-{r.id}.csv"})
