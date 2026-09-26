"""MSSP operations API — the provider's view across its customer portfolio.

All endpoints authorise against the caller's HOME tenant permissions
(``mssp:*``) and only ever touch tenants the caller can reach through
:mod:`astrasoc.services.tenancy` (descendants of the home tenant, subject to
each customer's delegation policy). Platform administrators see everything.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import get_current_principal
from ..db import get_db
from ..models import (
    ApprovalRequest,
    Connector,
    ConnectorHealth,
    DetectionRule,
    Incident,
    Notification,
    Role,
    ShiftHandover,
    Tenant,
    TenantAccessGrant,
    User,
)
from ..schemas.common import serialize, serialize_many
from ..services import audit
from ..services.metering import METRICS, period_of, usage_for
from ..services.mode import current_scope, get_mode
from ..services.sla import CLOSED, sla_report, sla_state
from ..services.tenancy import (
    accessible_tenants,
    delegation_policy,
    descendant_ids,
)
from ..services.tenants import (
    STATUSES,
    TenantError,
    create_user,
    export_tenant,
    provision_tenant,
    purge_tenant,
)
from ..services.tiers import FEATURES, TIERS, effective_sla, tenant_features

router = APIRouter(prefix="/api/v1/mssp", tags=["mssp"])


# --- Helpers -------------------------------------------------------------------
def _home_user(db: Session, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise HTTPException(401, detail="User not found")
    return user


def _portfolio(db: Session, principal: Principal, *, operational: bool = True) -> dict[uuid.UUID, Tenant]:
    """Customer tenants in the caller's portfolio.

    * operational (default): customers the caller can actually act in — this
      honours each customer's delegation policy and the caller's grants. Used
      for anything that exposes case content (queue, handover, content).
    * contractual: every descendant customer, for aggregate/contract views
      (usage, SLA figures, tenant lists) — only for staff who run the whole
      book of business (all_customers / billing / onboarding) or the
      platform operator; everyone else falls back to operational.
    """
    principal.require_home("mssp:portfolio")
    user = _home_user(db, principal)
    book_of_business = principal.is_platform_admin or any(
        principal.has_home(p) for p in ("mssp:all_customers", "mssp:billing", "mssp:onboard"))
    if not operational and book_of_business:
        if principal.is_platform_admin:
            rows = db.execute(select(Tenant).where(Tenant.kind == "customer")).scalars()
        else:
            ids = descendant_ids(db, principal.home_tenant_id)
            rows = db.execute(select(Tenant).where(Tenant.id.in_(ids),
                                                   Tenant.kind == "customer")).scalars() if ids else []
        return {t.id: t for t in rows}
    return {d.tenant.id: d.tenant for d in accessible_tenants(db, user, principal.home_permissions)
            if d.tenant.kind == "customer"}


def _managed(db: Session, principal: Principal, tenant_id: uuid.UUID) -> Tenant:
    """A tenant the caller administers contractually (descendant of home, or
    anything for a platform admin). Unlike delegated access, this does not
    depend on the customer's delegation policy — the provider always owns
    the contract."""
    t = db.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(404, detail="Tenant not found")
    if principal.is_platform_admin:
        return t
    if t.id not in descendant_ids(db, principal.home_tenant_id):
        raise HTTPException(404, detail="Tenant not found")
    return t


def _parse_period(period: str | None) -> tuple[str, datetime, datetime]:
    period = period or period_of()
    try:
        start = datetime.strptime(period + "-01", "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        raise HTTPException(422, detail="period must be YYYY-MM")
    end = (start + timedelta(days=32)).replace(day=1)
    return period, start, end


def _tenant_card(t: Tenant) -> dict:
    return {"id": str(t.id), "name": t.name, "slug": t.slug, "kind": t.kind, "status": t.status,
            "service_tier": t.service_tier, "region": t.region,
            "parent_id": str(t.parent_id) if t.parent_id else None,
            "branding": t.branding or {}}


# --- Portfolio -------------------------------------------------------------------
@router.get("/overview")
def overview(principal: Principal = Depends(get_current_principal),
             db: Session = Depends(get_db)) -> dict:
    # Aggregates only (counts, SLA figures) — contractual view.
    tenants = _portfolio(db, principal, operational=False)
    now = datetime.now(UTC)
    customers = []
    totals = {"open_incidents": 0, "critical_open": 0, "sla_breached": 0, "sla_at_risk": 0,
              "pending_approvals": 0, "unhealthy_connectors": 0}
    for tid, t in tenants.items():
        scope = current_scope(db, tid)
        open_incs = db.execute(select(Incident).where(
            Incident.tenant_id == tid, Incident.data_scope == scope,
            Incident.status.notin_(CLOSED))).scalars().all()
        by_sev: dict[str, int] = {}
        breached = at_risk = 0
        for inc in open_incs:
            by_sev[inc.severity] = by_sev.get(inc.severity, 0) + 1
            state = sla_state(inc, now)["overall"]
            breached += state == "breached"
            at_risk += state == "at_risk"
        approvals = db.execute(select(func.count()).select_from(ApprovalRequest).where(
            ApprovalRequest.tenant_id == tid, ApprovalRequest.status == "pending")).scalar() or 0
        conns = db.execute(select(Connector).where(Connector.tenant_id == tid,
                                                   Connector.enabled.is_(True))).scalars().all()
        unhealthy = 0
        for c in conns:
            latest = db.execute(select(ConnectorHealth).where(ConnectorHealth.connector_id == c.id)
                                .order_by(ConnectorHealth.checked_at.desc()).limit(1)).scalar_one_or_none()
            unhealthy += bool(latest and latest.state in ("unhealthy", "degraded"))
        last = max((i.updated_at for i in open_incs), default=None)
        card = _tenant_card(t) | {
            "mode": get_mode(db, tid).mode, "open_incidents": len(open_incs),
            "by_severity": by_sev, "sla_breached": breached, "sla_at_risk": at_risk,
            "pending_approvals": approvals, "enabled_connectors": len(conns),
            "unhealthy_connectors": unhealthy, "last_activity": last.isoformat() if last else None,
            "contract_end": t.contract_end.isoformat() if t.contract_end else None,
            "provider_access": delegation_policy(t)["allow_provider_access"],
        }
        # Health score: 100 minus weighted open risk — a triage aid, not a KPI.
        card["health_score"] = max(0, 100 - 25 * breached - 10 * by_sev.get("critical", 0)
                                   - 5 * by_sev.get("high", 0) - 5 * unhealthy)
        customers.append(card)
        totals["open_incidents"] += len(open_incs)
        totals["critical_open"] += by_sev.get("critical", 0)
        totals["sla_breached"] += breached
        totals["sla_at_risk"] += at_risk
        totals["pending_approvals"] += approvals
        totals["unhealthy_connectors"] += unhealthy
    customers.sort(key=lambda c: (c["health_score"], c["name"]))
    return {"customers": customers, "totals": totals | {"customers": len(customers)}}


@router.get("/queue")
def unified_queue(principal: Principal = Depends(get_current_principal),
                  db: Session = Depends(get_db),
                  severity: str | None = None, sla: str | None = None,
                  tenant: str | None = None, status: str | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)) -> dict:
    """One queue across every accessible customer, most urgent first."""
    tenants = _portfolio(db, principal)
    now = datetime.now(UTC)
    rank = {"breached": 0, "at_risk": 1, "on_track": 2, "met": 3, "n/a": 4}
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    items = []
    for tid, t in tenants.items():
        if tenant and tenant not in (str(tid), t.slug):
            continue
        q = select(Incident).where(Incident.tenant_id == tid,
                                   Incident.data_scope == current_scope(db, tid))
        q = q.where(Incident.status == status) if status else q.where(Incident.status.notin_(CLOSED))
        if severity:
            q = q.where(Incident.severity == severity)
        for inc in db.execute(q.limit(1000)).scalars():
            st = sla_state(inc, now)
            if sla and st["overall"] != sla:
                continue
            remaining = [x["minutes_remaining"] for x in (st["ack"], st["resolve"])
                         if x.get("minutes_remaining") is not None]
            items.append({
                "id": str(inc.id), "key": inc.key, "title": inc.title, "severity": inc.severity,
                "status": inc.status, "created_at": inc.created_at.isoformat(),
                "owner_id": str(inc.owner_id) if inc.owner_id else None,
                "tenant": {"id": str(tid), "name": t.name, "slug": t.slug,
                           "service_tier": t.service_tier},
                "sla": st, "_sort": (rank[st["overall"]], sev_rank.get(inc.severity, 5),
                                     min(remaining) if remaining else 1e9),
            })
    items.sort(key=lambda i: i["_sort"])
    total = len(items)
    page_items = items[(page - 1) * page_size: page * page_size]
    for i in page_items:
        i.pop("_sort")
    return {"items": page_items, "total": total, "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size}


@router.get("/sla")
def sla_compliance(principal: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db), period: str | None = None) -> dict:
    tenants = _portfolio(db, principal, operational=False)
    period, start, end = _parse_period(period)
    rows = sla_report(db, list(tenants), start, end)
    return {"period": period, "customers": rows}


@router.get("/usage")
def usage(principal: Principal = Depends(get_current_principal),
          db: Session = Depends(get_db), period: str | None = None,
          format: str = Query("json", pattern="^(json|csv)$")):
    principal.require_home("mssp:billing")
    tenants = _portfolio(db, principal, operational=False)
    period, _, _ = _parse_period(period)
    data = usage_for(db, list(tenants), period)
    rows = [{"tenant_id": str(tid), "tenant": tenants[tid].name, "slug": tenants[tid].slug,
             "service_tier": tenants[tid].service_tier, "region": tenants[tid].region,
             **{m: data[tid][m] for m in METRICS}} for tid in tenants]
    rows.sort(key=lambda r: r["tenant"])
    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["period", "tenant", "slug", "service_tier", "region",
                                            *METRICS])
        w.writeheader()
        for r in rows:
            w.writerow({"period": period, **{k: r[k] for k in w.fieldnames if k != "period"}})
        return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={
            "content-disposition": f"attachment; filename=usage-{period}.csv"})
    return {"period": period, "metrics": METRICS, "customers": rows}


# --- Tenant lifecycle -------------------------------------------------------------
@router.get("/catalog")
def catalog(principal: Principal = Depends(get_current_principal)) -> dict:
    principal.require_home("mssp:portfolio")
    return {"tiers": TIERS, "features": FEATURES, "statuses": list(STATUSES)}


@router.get("/tenants")
def list_tenants(principal: Principal = Depends(get_current_principal),
                 db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:portfolio")
    if principal.is_platform_admin:
        rows = db.execute(select(Tenant).order_by(Tenant.name)).scalars().all()
    else:
        ids = descendant_ids(db, principal.home_tenant_id) | {principal.home_tenant_id}
        rows = db.execute(select(Tenant).where(Tenant.id.in_(ids)).order_by(Tenant.name)).scalars().all()
    out = []
    for t in rows:
        card = _tenant_card(t) | {
            "contract_start": t.contract_start.isoformat() if t.contract_start else None,
            "contract_end": t.contract_end.isoformat() if t.contract_end else None,
            "users": db.execute(select(func.count()).select_from(User).where(
                User.tenant_id == t.id)).scalar() or 0,
            "provider_access": delegation_policy(t)["allow_provider_access"],
        }
        out.append(card)
    return {"items": out}


@router.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: uuid.UUID, principal: Principal = Depends(get_current_principal),
               db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:portfolio")
    t = _managed(db, principal, tenant_id)
    data = serialize(t)
    data["effective_sla"] = effective_sla(t)
    data["features"] = sorted(tenant_features(t))
    data["delegation"] = delegation_policy(t)
    data["mode"] = get_mode(db, t.id).to_dict()
    return data


@router.post("/tenants", status_code=201)
def onboard_tenant(payload: dict = Body(...),
                   principal: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db)) -> dict:
    """Onboard a customer (or reseller) under the caller's provider tenant or
    one of its resellers, optionally creating the first customer admin."""
    principal.require_home("mssp:onboard")
    home = db.get(Tenant, principal.home_tenant_id)
    if home is None or (home.kind not in ("provider", "reseller") and not principal.is_platform_admin):
        raise HTTPException(403, detail="Only provider or reseller tenants can onboard customers.")
    parent_id = uuid.UUID(payload["parent_id"]) if payload.get("parent_id") else home.id
    if parent_id != home.id:
        _managed(db, principal, parent_id)
    kind = payload.get("kind", "customer")
    if kind not in ("customer", "reseller"):
        raise HTTPException(422, detail="kind must be 'customer' or 'reseller'")
    try:
        t = provision_tenant(
            db, name=str(payload.get("name", "")).strip(), slug=str(payload.get("slug", "")),
            kind=kind, parent_id=parent_id, tier=payload.get("service_tier", "professional"),
            region=payload.get("region", "global"), sla_policy=payload.get("sla_policy"),
            contacts=payload.get("contacts"), branding=payload.get("branding"),
            status=payload.get("status", "onboarding"),
            settings={"delegation": {"allow_provider_access": True},
                      "customer_approval_actions": payload.get("customer_approval_actions", [])},
            contract_start=_dt(payload.get("contract_start")),
            contract_end=_dt(payload.get("contract_end")),
        )
        admin = payload.get("admin")
        admin_user = None
        if admin:
            admin_user = create_user(
                db, t, email=admin.get("email", ""), full_name=admin.get("full_name", ""),
                password=admin.get("password", ""),
                roles=["customer_admin" if kind == "customer" else "provider_admin"])
    except TenantError as exc:
        db.rollback()
        raise HTTPException(409 if exc.code == "conflict" else 422,
                            detail={"error": exc.code, "message": exc.message})
    audit.record(db, action="mssp.tenant_onboarded", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.home_tenant_id,
                 resource_type="tenant", resource_id=str(t.id),
                 detail={"name": t.name, "slug": t.slug, "kind": kind, "tier": t.service_tier,
                         "admin": admin_user.email if admin_user else None})
    db.commit()
    return _tenant_card(t)


def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value))
    except ValueError:
        raise HTTPException(422, detail=f"Invalid ISO date: {value}")
    return d if d.tzinfo else d.replace(tzinfo=UTC)


@router.patch("/tenants/{tenant_id}")
def update_tenant(tenant_id: uuid.UUID, payload: dict = Body(...),
                  principal: Principal = Depends(get_current_principal),
                  db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:onboard")
    t = _managed(db, principal, tenant_id)
    if "service_tier" in payload:
        if payload["service_tier"] not in TIERS:
            raise HTTPException(422, detail=f"service_tier must be one of {sorted(TIERS)}")
        t.service_tier = payload["service_tier"]
    if "status" in payload:
        if payload["status"] not in STATUSES:
            raise HTTPException(422, detail=f"status must be one of {STATUSES}")
        t.status = payload["status"]
        t.is_active = t.status in ("active", "onboarding")
    for field in ("name", "region", "contacts", "branding"):
        if field in payload:
            setattr(t, field, payload[field])
    if "sla_policy" in payload:
        pol = payload["sla_policy"] or {}
        for tgt in pol.values():
            if not isinstance(tgt, dict) or any(int(v) <= 0 for v in tgt.values()):
                raise HTTPException(422, detail="SLA targets must be positive minutes")
        t.sla_policy = pol
    for field in ("contract_start", "contract_end"):
        if field in payload:
            setattr(t, field, _dt(payload[field]))
    new_settings = dict(t.settings or {})
    if "feature_overrides" in payload:
        bad = [f for f in (payload["feature_overrides"] or {}) if f not in FEATURES]
        if bad:
            raise HTTPException(422, detail=f"Unknown features: {bad}")
        new_settings["feature_overrides"] = payload["feature_overrides"]
    if "customer_approval_actions" in payload:
        new_settings["customer_approval_actions"] = list(payload["customer_approval_actions"] or [])
    t.settings = new_settings
    audit.record(db, action="mssp.tenant_updated", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.home_tenant_id,
                 resource_type="tenant", resource_id=str(t.id), detail={"fields": list(payload)})
    # The customer sees contract changes in its own audit trail too.
    audit.record(db, action="tenant.contract_updated", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=t.id, resource_type="tenant",
                 resource_id=str(t.id), detail={"fields": list(payload)})
    db.commit()
    return get_tenant(tenant_id, principal, db)


@router.post("/tenants/{tenant_id}/suspend")
def suspend(tenant_id: uuid.UUID, payload: dict | None = Body(None),
            principal: Principal = Depends(get_current_principal),
            db: Session = Depends(get_db)) -> dict:
    return update_tenant(tenant_id, {"status": "suspended"}, principal, db) | {
        "note": (payload or {}).get("reason", "")}


@router.post("/tenants/{tenant_id}/activate")
def activate(tenant_id: uuid.UUID, principal: Principal = Depends(get_current_principal),
             db: Session = Depends(get_db)) -> dict:
    return update_tenant(tenant_id, {"status": "active"}, principal, db)


@router.get("/tenants/{tenant_id}/export")
def export(tenant_id: uuid.UUID, principal: Principal = Depends(get_current_principal),
           db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:onboard")
    t = _managed(db, principal, tenant_id)
    bundle = export_tenant(db, t)
    audit.record(db, action="mssp.tenant_exported", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=t.id, resource_type="tenant",
                 resource_id=str(t.id))
    db.commit()
    return bundle


@router.delete("/tenants/{tenant_id}")
def offboard(tenant_id: uuid.UUID, payload: dict = Body(...),
             principal: Principal = Depends(get_current_principal),
             db: Session = Depends(get_db)) -> dict:
    """Irreversibly purge a customer. Requires the tenant to be suspended or
    offboarding and the caller to type the tenant slug to confirm."""
    principal.require_home("mssp:onboard")
    t = _managed(db, principal, tenant_id)
    if t.id == principal.home_tenant_id or t.kind == "provider":
        raise HTTPException(400, detail="The provider tenant cannot be offboarded.")
    if t.status not in ("suspended", "offboarding"):
        raise HTTPException(409, detail="Suspend the tenant before offboarding it.")
    if payload.get("confirm") != t.slug:
        raise HTTPException(422, detail="Confirm by sending {\"confirm\": \"<tenant slug>\"}.")
    name, slug = t.name, t.slug
    try:
        counts = purge_tenant(db, t)
    except TenantError as exc:
        db.rollback()
        raise HTTPException(409, detail={"error": exc.code, "message": exc.message})
    audit.record(db, action="mssp.tenant_offboarded", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.home_tenant_id,
                 resource_type="tenant", resource_id=str(tenant_id),
                 detail={"name": name, "slug": slug, "deleted": counts})
    db.commit()
    return {"status": "offboarded", "tenant": slug, "deleted": counts}


# --- Delegated access grants -------------------------------------------------------
@router.get("/staff")
def staff(principal: Principal = Depends(get_current_principal),
          db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:grants")
    rows = db.execute(select(User).where(User.tenant_id == principal.home_tenant_id)
                      .order_by(User.email)).scalars().all()
    return {"items": [{"id": str(u.id), "email": u.email, "full_name": u.full_name,
                       "is_active": u.is_active} for u in rows]}


@router.get("/grants")
def list_grants(principal: Principal = Depends(get_current_principal),
                db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:grants")
    rows = db.execute(select(TenantAccessGrant).where(
        TenantAccessGrant.provider_tenant_id == principal.home_tenant_id)
        .order_by(TenantAccessGrant.created_at.desc())).scalars().all()
    now = datetime.now(UTC)
    out = []
    for g in rows:
        d = serialize(g)
        u, t = db.get(User, g.user_id), db.get(Tenant, g.customer_tenant_id)
        d["user_email"] = u.email if u else None
        d["tenant"] = t.name if t else None
        d["active"] = g.revoked_at is None and (g.expires_at is None or g.expires_at > now)
        out.append(d)
    return {"items": out}


@router.post("/grants", status_code=201)
def create_grant(payload: dict = Body(...),
                 principal: Principal = Depends(get_current_principal),
                 db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:grants")
    try:
        user = db.get(User, uuid.UUID(str(payload.get("user_id"))))
        tenant_id = uuid.UUID(str(payload.get("tenant_id")))
    except ValueError:
        raise HTTPException(422, detail="user_id and tenant_id must be UUIDs")
    if user is None or user.tenant_id != principal.home_tenant_id:
        raise HTTPException(404, detail="Staff user not found in your provider tenant")
    t = _managed(db, principal, tenant_id)
    if t.kind != "customer":
        raise HTTPException(422, detail="Grants target customer tenants")
    role_name = str(payload.get("role", ""))
    role = db.execute(select(Role).where(Role.tenant_id == t.id, Role.name == role_name)).scalar_one_or_none()
    if role is None:
        raise HTTPException(422, detail=f"Role '{role_name}' does not exist in the customer tenant")
    if role_name in ("tenant_admin", "customer_admin"):
        raise HTTPException(422, detail="Provider staff cannot be granted customer admin roles")
    reason = str(payload.get("reason", "")).strip()
    if len(reason) < 5:
        raise HTTPException(422, detail="A justification (reason) is required")
    hours = payload.get("expires_in_hours")
    expires_at = datetime.now(UTC) + timedelta(hours=int(hours)) if hours else None
    g = TenantAccessGrant(provider_tenant_id=principal.home_tenant_id, customer_tenant_id=t.id,
                          user_id=user.id, role_name=role_name, reason=reason,
                          granted_by=principal.user_id, expires_at=expires_at)
    db.add(g)
    db.flush()
    for tid in (principal.home_tenant_id, t.id):  # both sides see the grant
        audit.record(db, action="mssp.access_granted", actor_id=principal.user_id,
                     actor_label=principal.label, tenant_id=tid, resource_type="access_grant",
                     resource_id=str(g.id), detail={"user": user.email, "tenant": t.slug,
                                                     "role": role_name, "reason": reason,
                                                     "expires_at": expires_at.isoformat() if expires_at else None})
    db.commit()
    return serialize(g)


@router.delete("/grants/{grant_id}")
def revoke_grant(grant_id: uuid.UUID, principal: Principal = Depends(get_current_principal),
                 db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:grants")
    g = db.get(TenantAccessGrant, grant_id)
    if g is None or g.provider_tenant_id != principal.home_tenant_id:
        raise HTTPException(404, detail="Grant not found")
    g.revoked_at = g.revoked_at or datetime.now(UTC)
    for tid in (principal.home_tenant_id, g.customer_tenant_id):
        audit.record(db, action="mssp.access_revoked", actor_id=principal.user_id,
                     actor_label=principal.label, tenant_id=tid, resource_type="access_grant",
                     resource_id=str(g.id))
    db.commit()
    return {"status": "revoked"}


# --- Managed detection content --------------------------------------------------------
@router.get("/content/detections")
def content_library(principal: Principal = Depends(get_current_principal),
                    db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:content")
    rows = db.execute(select(DetectionRule).where(
        DetectionRule.tenant_id == principal.home_tenant_id).order_by(DetectionRule.name)).scalars().all()
    return {"items": serialize_many(rows)}


@router.post("/content/detections/{rule_id}/deploy")
def deploy_content(rule_id: uuid.UUID, payload: dict = Body(...),
                   principal: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db)) -> dict:
    """Publish a provider-managed detection to customers. Only approved or
    deployed rules can be distributed; customers receive a managed copy
    (tagged with its source and version) that is re-synced on redeploy."""
    principal.require_home("mssp:content")
    src = db.get(DetectionRule, rule_id)
    if src is None or src.tenant_id != principal.home_tenant_id:
        raise HTTPException(404, detail="Rule not found in your content library")
    if src.status not in ("approved", "deployed"):
        raise HTTPException(409, detail="Only approved/deployed rules can be distributed")
    portfolio = _portfolio(db, principal)
    if payload.get("all"):
        targets = list(portfolio)
    else:
        try:
            targets = [uuid.UUID(x) for x in payload.get("tenant_ids") or []]
        except ValueError:
            raise HTTPException(422, detail="tenant_ids must be UUIDs")
    results = []
    for tid in targets:
        if tid not in portfolio:
            results.append({"tenant_id": str(tid), "status": "skipped", "reason": "not accessible"})
            continue
        if src.ai_generated and not src.approved_by:
            results.append({"tenant_id": str(tid), "status": "skipped", "reason": "unapproved AI rule"})
            continue
        existing = db.execute(select(DetectionRule).where(
            DetectionRule.tenant_id == tid, DetectionRule.key == src.key)).scalar_one_or_none()
        fields = {"name": src.name, "description": src.description, "sigma": src.sigma,
                  "matcher": src.matcher, "severity": src.severity,
                  "attack_techniques": src.attack_techniques, "data_sources": src.data_sources,
                  "false_positives": src.false_positives, "version": src.version,
                  "status": "deployed", "enabled": True,
                  "deployment_target": f"managed:{principal.home_tenant_slug}",
                  "approved_by": src.approved_by or principal.email,
                  "author": src.author}
        if existing is None:
            db.add(DetectionRule(tenant_id=tid, key=src.key, **fields,
                                 version_history=[{"version": src.version, "source": str(src.id)}]))
            status = "created"
        else:
            if existing.deployment_target and not existing.deployment_target.startswith("managed:"):
                results.append({"tenant_id": str(tid), "status": "skipped",
                                "reason": "customer-owned rule with the same key"})
                continue
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.exceptions = existing.exceptions  # customer tuning is preserved
            existing.version_history = [*(existing.version_history or []),
                                        {"version": src.version, "source": str(src.id)}]
            status = "updated"
        audit.record(db, action="mssp.content_deployed", actor_id=principal.user_id,
                     actor_label=principal.label, tenant_id=tid, resource_type="detection_rule",
                     resource_id=src.key, detail={"version": src.version, "status": status})
        results.append({"tenant_id": str(tid), "tenant": portfolio[tid].name, "status": status})
    db.commit()
    return {"rule": src.key, "version": src.version, "results": results}


# --- Shift handover ---------------------------------------------------------------
@router.get("/handovers")
def list_handovers(principal: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db), limit: int = Query(20, le=100)) -> dict:
    principal.require_home("mssp:handover")
    rows = db.execute(select(ShiftHandover).where(
        ShiftHandover.provider_tenant_id == principal.home_tenant_id)
        .order_by(ShiftHandover.created_at.desc()).limit(limit)).scalars().all()
    return {"items": serialize_many(rows)}


@router.post("/handovers", status_code=201)
def create_handover(payload: dict = Body(...),
                    principal: Principal = Depends(get_current_principal),
                    db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:handover")
    portfolio = _portfolio(db, principal) if principal.has_home("mssp:portfolio") else {}
    items = []
    for it in payload.get("open_items") or []:
        inc = None
        if it.get("incident_id"):
            try:
                inc = db.get(Incident, uuid.UUID(str(it["incident_id"])))
            except ValueError:
                inc = None
            if inc is None or inc.tenant_id not in portfolio:
                raise HTTPException(422, detail="Handover items may only reference accessible incidents")
        items.append({"tenant_id": str(inc.tenant_id) if inc else it.get("tenant_id"),
                      "incident_id": str(inc.id) if inc else None,
                      "incident_key": inc.key if inc else None,
                      "note": str(it.get("note", ""))[:2000], "owner": it.get("owner")})
    h = ShiftHandover(provider_tenant_id=principal.home_tenant_id, author_id=principal.user_id,
                      author_label=principal.label, shift=str(payload.get("shift", ""))[:40],
                      summary=str(payload.get("summary", "")), open_items=items)
    db.add(h)
    db.flush()
    audit.record(db, action="mssp.handover_created", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.home_tenant_id,
                 resource_type="shift_handover", resource_id=str(h.id))
    db.commit()
    return serialize(h)


@router.post("/handovers/{handover_id}/acknowledge")
def ack_handover(handover_id: uuid.UUID, principal: Principal = Depends(get_current_principal),
                 db: Session = Depends(get_db)) -> dict:
    principal.require_home("mssp:handover")
    h = db.get(ShiftHandover, handover_id)
    if h is None or h.provider_tenant_id != principal.home_tenant_id:
        raise HTTPException(404, detail="Handover not found")
    if h.author_id == principal.user_id:
        raise HTTPException(409, detail="The incoming shift must acknowledge, not the author")
    h.acknowledged_by, h.acknowledged_at = principal.user_id, datetime.now(UTC)
    db.commit()
    return serialize(h)


# --- Service reports ------------------------------------------------------------------
@router.post("/reports/service")
def service_reports(payload: dict = Body(default={}),
                    principal: Principal = Depends(get_current_principal),
                    db: Session = Depends(get_db)) -> dict:
    """Generate the monthly managed-service report for each (or selected)
    customer. Reports are stored in the customer tenant so the customer's
    own users can read them."""
    from ..services.reporting import generate_report

    portfolio = _portfolio(db, principal)
    period, _, _ = _parse_period(payload.get("period"))
    wanted = {uuid.UUID(x) for x in payload.get("tenant_ids") or []} or set(portfolio)
    out = []
    for tid in wanted & set(portfolio):
        rep = generate_report(db, tid, "service_report", current_scope(db, tid),
                              generated_by=principal.user_id, parameters={"period": period})
        out.append({"tenant": portfolio[tid].name, "report_id": str(rep.id), "title": rep.title})
    audit.record(db, action="mssp.service_reports_generated", actor_id=principal.user_id,
                 actor_label=principal.label, tenant_id=principal.home_tenant_id,
                 detail={"period": period, "count": len(out)})
    db.commit()
    return {"period": period, "reports": out}


# --- Provider notifications (incl. customer escalations) ---------------------------------
@router.get("/notifications")
def provider_notifications(principal: Principal = Depends(get_current_principal),
                           db: Session = Depends(get_db), unread: bool = False,
                           limit: int = Query(50, le=200)) -> dict:
    principal.require_home("mssp:portfolio")
    q = select(Notification).where(Notification.tenant_id == principal.home_tenant_id)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    rows = db.execute(q.order_by(Notification.created_at.desc()).limit(limit)).scalars().all()
    return {"items": serialize_many(rows)}
