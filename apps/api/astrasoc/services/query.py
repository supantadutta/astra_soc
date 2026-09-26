"""Query Workbench engine over the normalized event store.

This is deliberately a small, honest engine — not a full SPL/KQL/Lucene
implementation. It extracts ``field <op> value`` predicates from a query in
any of the supported languages, maps vendor field names onto the normalized
event schema, and executes them as parameterised SQL against
``security_events`` (tenant- and scope-filtered, row-capped). Anything it
cannot translate is returned in ``unsupported_terms`` so the analyst knows
exactly which part of the query was NOT applied.

Supported operators: ``=`` / ``==`` / ``:`` (case-insensitive equality),
``!=`` (inequality), ``~`` / ``contains`` / ``has`` (substring).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import SecurityEvent

# vendor / language field names -> normalized column
FIELD_ALIASES: dict[str, str] = {
    **{k: "host_name" for k in ("host", "host_name", "hostname", "computername", "devicename",
                                "computer", "device", "host.name")},
    **{k: "user_name" for k in ("user", "user_name", "username", "userprincipalname", "account",
                                "accountname", "targetusername", "user.name")},
    **{k: "src_ip" for k in ("src_ip", "src", "source_ip", "sourceip", "ipaddress", "client_ip",
                             "source.ip", "callerip")},
    **{k: "dst_ip" for k in ("dst_ip", "dst", "dest_ip", "destinationip", "remoteip",
                             "destination.ip", "dest")},
    **{k: "severity" for k in ("severity", "level", "sev")},
    **{k: "source" for k in ("source", "vendor", "product", "sourcetype", "index")},
    **{k: "activity" for k in ("activity", "action", "eventtype", "event_type", "event.action",
                               "operation", "operationname")},
}
_TERM = re.compile(
    r"""(?P<field>[A-Za-z_][\w.]*)\s*(?P<op>==|!=|=|:|~|\bcontains\b|\bhas\b)\s*"""
    r"""(?P<value>"[^"]*"|'[^']*'|[^\s|,)]+)""", re.IGNORECASE)
_NOISE = {"search", "where", "and", "select", "from", "events", "table", "|", "securityevent",
          "signinlogs", "*", "limit", "order", "by", "desc", "asc", "take", "sort"}


@dataclass
class QueryPlan:
    filters: list[tuple[str, str, str]] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def plan(query: str) -> QueryPlan:
    p = QueryPlan()
    consumed: list[tuple[int, int]] = []
    for m in _TERM.finditer(query or ""):
        fname = m.group("field").lower()
        op = m.group("op").lower()
        value = m.group("value").strip("'\"")
        column = FIELD_ALIASES.get(fname)
        if column is None:
            p.unsupported.append(m.group(0))
        else:
            norm = {"==": "eq", "=": "eq", ":": "eq", "!=": "ne", "~": "contains",
                    "contains": "contains", "has": "contains"}[op]
            p.filters.append((column, norm, value))
        consumed.append(m.span())
    # Anything left over that is not structural noise is reported.
    rest = query or ""
    for start, end in sorted(consumed, reverse=True):
        rest = rest[:start] + " " + rest[end:]
    for token in re.split(r"[\s|(),;]+", rest):
        t = token.strip()
        if t and t.lower() not in _NOISE and not t.isdigit():
            p.unsupported.append(t)
    return p


def execute(db: Session, tenant_id: uuid.UUID, scope: str, query: str, *,
            limit: int = 100, hours: int | None = None) -> dict:
    qp = plan(query)
    stmt = select(SecurityEvent).where(SecurityEvent.tenant_id == tenant_id,
                                       SecurityEvent.data_scope == scope)
    if hours:
        stmt = stmt.where(SecurityEvent.event_time >= datetime.now(UTC) - timedelta(hours=hours))
    for column, op, value in qp.filters:
        col = func.lower(getattr(SecurityEvent, column))
        v = value.lower()
        if op == "eq":
            stmt = stmt.where(col == v)
        elif op == "ne":
            stmt = stmt.where((col != v) | (getattr(SecurityEvent, column).is_(None)))
        else:
            stmt = stmt.where(col.contains(v, autoescape=True))
    limit = max(1, min(int(limit), 1000))
    rows = db.execute(stmt.order_by(SecurityEvent.event_time.desc()).limit(limit)).scalars().all()
    return {
        "applied_filters": [{"field": c, "op": o, "value": v} for c, o, v in qp.filters],
        "unsupported_terms": qp.unsupported,
        "row_count": len(rows),
        "results": [{"time": e.event_time.isoformat(), "source": e.source, "activity": e.activity,
                     "severity": e.severity, "host": e.host_name, "user": e.user_name,
                     "src_ip": e.src_ip, "dst_ip": e.dst_ip} for e in rows],
    }
