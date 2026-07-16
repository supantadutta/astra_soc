"""Entities API: entity list, entity graph, and attack-path exploration."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..listing import paginate
from ..models import Entity, EntityRelationship
from ..schemas.common import serialize
from ..services.mode import current_scope

router = APIRouter(prefix="/api/v1/entities", tags=["entities"])


@router.get("")
def list_entities(
    principal: Principal = Depends(require_permission("entity:read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    kind: str | None = None, q: str | None = None, sort: str | None = None, order: str = "desc",
) -> dict:
    scope = current_scope(db)
    filters = [Entity.kind == kind] if kind else []
    return paginate(db, Entity, tenant_id=principal.tenant_id, scope=scope, filters=filters,
                    search=q, search_fields=["value", "display_name"],
                    sort=sort or "risk_score", order=order, page=page, page_size=page_size)


@router.get("/graph")
def entity_graph(
    principal: Principal = Depends(require_permission("entity:read")),
    db: Session = Depends(get_db),
    incident_id: uuid.UUID | None = None, limit: int = Query(300, le=1000),
) -> dict:
    """Nodes + edges for the entity graph / attack-path explorer."""
    scope = current_scope(db)
    rq = select(EntityRelationship).where(
        EntityRelationship.tenant_id == principal.tenant_id,
        EntityRelationship.data_scope == scope)
    if incident_id:
        rq = rq.where(EntityRelationship.incident_id == incident_id)
    rels = db.execute(rq.limit(limit)).scalars().all()
    ids = {r.src_entity_id for r in rels} | {r.dst_entity_id for r in rels}
    ents = db.execute(select(Entity).where(Entity.id.in_(ids))).scalars().all() if ids else []
    return {
        "nodes": [{"id": str(e.id), "label": e.display_name or e.value, "kind": e.kind,
                   "risk": e.risk_score, "criticality": e.criticality,
                   "internal": e.is_internal} for e in ents],
        "edges": [{"id": str(r.id), "source": str(r.src_entity_id),
                   "target": str(r.dst_entity_id), "type": r.relationship_type,
                   "weight": r.weight} for r in rels],
    }


@router.get("/attack-paths")
def attack_paths(
    principal: Principal = Depends(require_permission("entity:read")),
    db: Session = Depends(get_db),
    incident_id: uuid.UUID | None = None,
) -> dict:
    """Derive simple attack paths (chains toward high-criticality assets)."""
    scope = current_scope(db)
    rq = select(EntityRelationship).where(
        EntityRelationship.tenant_id == principal.tenant_id,
        EntityRelationship.data_scope == scope)
    if incident_id:
        rq = rq.where(EntityRelationship.incident_id == incident_id)
    rels = db.execute(rq.limit(500)).scalars().all()
    ids = {r.src_entity_id for r in rels} | {r.dst_entity_id for r in rels}
    ents = {e.id: e for e in db.execute(select(Entity).where(Entity.id.in_(ids))).scalars()} \
        if ids else {}

    # Build adjacency and walk from external/low nodes to critical assets.
    adj: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
    for r in rels:
        adj.setdefault(r.src_entity_id, []).append((r.dst_entity_id, r.relationship_type))
    paths = []
    crit = {"high", "critical"}
    for start in list(adj)[:50]:
        stack = [(start, [start], [])]
        while stack:
            node, path, edges = stack.pop()
            if len(path) > 6:
                continue
            e = ents.get(node)
            if e and e.criticality in crit and len(path) > 1:
                paths.append({
                    "nodes": [{"id": str(n), "label": ents[n].display_name if n in ents else str(n),
                               "criticality": ents[n].criticality if n in ents else "low"}
                              for n in path],
                    "edges": edges,
                    "risk": max((ents[n].risk_score for n in path if n in ents), default=0),
                })
                continue
            for nxt, rel in adj.get(node, []):
                if nxt not in path:
                    stack.append((nxt, path + [nxt], edges + [rel]))
    paths.sort(key=lambda p: p["risk"], reverse=True)
    return {"paths": paths[:20], "count": len(paths)}


@router.get("/{entity_id}")
def get_entity(entity_id: uuid.UUID,
               principal: Principal = Depends(require_permission("entity:read")),
               db: Session = Depends(get_db)) -> dict:
    scope = current_scope(db)
    e = db.get(Entity, entity_id)
    if not e or e.tenant_id != principal.tenant_id or e.data_scope != scope:
        raise HTTPException(404, detail="Entity not found")
    rels = db.execute(select(EntityRelationship).where(
        or_(EntityRelationship.src_entity_id == e.id,
            EntityRelationship.dst_entity_id == e.id))).scalars().all()
    return {"entity": serialize(e),
            "relationships": [{"source": str(r.src_entity_id), "target": str(r.dst_entity_id),
                               "type": r.relationship_type} for r in rels]}
