"""Knowledge & Memory API: documents, ingestion, retrieval (tenant-scoped)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import KnowledgeDocument
from ..schemas.common import serialize
from ..services import audit, knowledge

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

MEMORY_SCOPES = ["incident_memory", "tenant_knowledge", "global_knowledge",
                 "playbook_knowledge", "detection_knowledge", "threat_intel_knowledge"]


@router.get("/scopes")
def scopes(principal: Principal = Depends(require_permission("knowledge:read"))) -> dict:
    return {"scopes": MEMORY_SCOPES}


@router.get("/documents")
def list_documents(principal: Principal = Depends(require_permission("knowledge:read")),
                   db: Session = Depends(get_db),
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                   scope: str | None = None, q: str | None = None) -> dict:
    from sqlalchemy import or_
    filters = [or_(KnowledgeDocument.tenant_id == principal.tenant_id,
                   KnowledgeDocument.is_global.is_(True))]
    if scope:
        filters.append(KnowledgeDocument.scope == scope)
    # tenant filter handled via explicit or_, so pass tenant_id=None
    return paginate(db, KnowledgeDocument, tenant_id=None, filters=filters,
                    search=q, search_fields=["title", "body", "source"],
                    page=page, page_size=page_size, exclude={"body"})


@router.post("/documents")
def create_document(payload: dict,
                    principal: Principal = Depends(require_permission("knowledge:write")),
                    db: Session = Depends(get_db)) -> dict:
    scope = payload.get("scope", "tenant_knowledge")
    if scope not in MEMORY_SCOPES:
        raise HTTPException(422, detail="Invalid memory scope")
    if scope == "global_knowledge" and not principal.is_platform_admin:
        raise HTTPException(403, detail="Only the platform operator can publish global knowledge.")
    if not str(payload.get("title", "")).strip():
        raise HTTPException(422, detail="title is required")
    classification = payload.get("classification", "internal")
    if classification not in principal.allowed_classifications:
        raise HTTPException(403, detail="You cannot store content above your classification clearance.")
    doc = knowledge.ingest_document(
        db, principal.tenant_id, title=str(payload["title"]).strip()[:300], body=payload.get("body", ""),
        scope=scope, classification=classification,
        source=payload.get("source", ""), author=principal.email,
        # Global knowledge is visible to every tenant, so only the platform
        # operator may publish it.
        is_global=bool(payload.get("is_global")) and principal.is_platform_admin,
    )
    audit.record(db, action="knowledge.ingested", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="knowledge_document",
                 resource_id=str(doc.id), detail={"scope": scope})
    db.commit()
    return serialize(doc, exclude={"body"})


@router.post("/search")
def search(payload: dict,
           principal: Principal = Depends(require_permission("knowledge:read")),
           db: Session = Depends(get_db)) -> dict:
    results = knowledge.search(
        db, principal.tenant_id, payload.get("query", ""),
        scopes=payload.get("scopes"),
        allowed_classifications=principal.allowed_classifications,
        limit=max(1, min(int(payload.get("limit", 8)), 50)),
    )
    return {"results": results}


@router.delete("/documents/{document_id}")
def delete_document(document_id: uuid.UUID,
                    principal: Principal = Depends(require_permission("knowledge:write")),
                    db: Session = Depends(get_db)) -> dict:
    doc = db.get(KnowledgeDocument, document_id)
    if not doc or doc.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="Document not found")
    db.delete(doc)
    audit.record(db, action="knowledge.deleted", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="knowledge_document",
                 resource_id=str(document_id))
    db.commit()
    return {"status": "deleted"}
