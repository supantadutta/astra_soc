"""Backend-enforced DEMO / LIVE operating mode.

The operating mode is a *server-side*, **per-tenant** state stored in
``SystemSetting`` (``tenant_id`` + key ``operating_mode``) — not a frontend
toggle. One tenant switching to LIVE never changes another tenant's mode. A
platform-wide row (``tenant_id IS NULL``) acts as the default for tenants that
have never switched. Everything downstream reads it:

* Data queries filter by ``data_scope`` matching the current mode, so demo and
  live rows never mix.
* The response gateway refuses to send production-changing actions while in
  DEMO mode; in DEMO every action is simulated and clearly labelled.
* Switching DEMO -> LIVE requires the ``mode:manage`` permission, an explicit
  confirmation, and passing readiness checks.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Connector, ModelProvider, SystemSetting

MODE_KEY = "operating_mode"


@dataclass
class ModeState:
    mode: str  # "DEMO" | "LIVE"
    changed_at: str | None = None
    changed_by: str | None = None
    ai_enabled: bool = True
    llm_strategy: str = "simulated"  # simulated|hosted|private|hybrid|disabled
    degraded: bool = False
    degraded_reasons: list[str] = field(default_factory=list)

    @property
    def is_live(self) -> bool:
        return self.mode == "LIVE"

    @property
    def is_demo(self) -> bool:
        return self.mode == "DEMO"

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "is_live": self.is_live,
            "changed_at": self.changed_at,
            "changed_by": self.changed_by,
            "ai_enabled": self.ai_enabled,
            "llm_strategy": self.llm_strategy,
            "degraded": self.degraded,
            "degraded_reasons": self.degraded_reasons,
            "allow_live_mode": settings.allow_live_mode,
        }


def _get_setting(db: Session, key: str, tenant_id: uuid.UUID | None = None) -> SystemSetting | None:
    cond = SystemSetting.tenant_id.is_(None) if tenant_id is None else SystemSetting.tenant_id == tenant_id
    return db.execute(
        select(SystemSetting).where(cond, SystemSetting.key == key)
    ).scalar_one_or_none()


def get_mode(db: Session, tenant_id: uuid.UUID | None = None) -> ModeState:
    row = _get_setting(db, MODE_KEY, tenant_id) if tenant_id is not None else None
    if row is None:
        row = _get_setting(db, MODE_KEY)
    if row is None:
        return ModeState(mode=settings.default_mode)
    v = row.value or {}
    return ModeState(
        mode=v.get("mode", settings.default_mode),
        changed_at=v.get("changed_at"),
        changed_by=v.get("changed_by"),
        ai_enabled=v.get("ai_enabled", True),
        llm_strategy=v.get("llm_strategy", "simulated"),
        degraded=v.get("degraded", False),
        degraded_reasons=v.get("degraded_reasons", []),
    )


def current_scope(db: Session, tenant_id: uuid.UUID | None = None) -> str:
    """The ``data_scope`` value the tenant's current mode operates on."""
    return "LIVE" if get_mode(db, tenant_id).is_live else "DEMO"


@dataclass
class ReadinessCheck:
    name: str
    passed: bool
    detail: str
    required: bool = True


def live_readiness(db: Session, tenant_id: uuid.UUID) -> list[ReadinessCheck]:
    """Checks that must pass before activating LIVE mode.

    These are honest checks against real configuration — they do not fabricate
    a ready state.
    """
    checks: list[ReadinessCheck] = []

    if not settings.allow_live_mode:
        checks.append(ReadinessCheck(
            "live_mode_allowed", False,
            "This deployment is hard-locked to DEMO (ASTRASOC_ALLOW_LIVE_MODE=false).",
        ))

    # At least one enabled, non-mock connector must exist to have real data.
    live_connectors = db.execute(
        select(Connector).where(Connector.tenant_id == tenant_id, Connector.enabled.is_(True),
                                Connector.use_mock.is_(False))
    ).scalars().all()
    checks.append(ReadinessCheck(
        "live_connector_configured",
        len(live_connectors) > 0,
        f"{len(live_connectors)} enabled non-mock connector(s) configured."
        if live_connectors else
        "No enabled non-mock connector. Live mode would have no real data source.",
        required=True,
    ))

    # Persistent datastore for production (SQLite is demo-only).
    checks.append(ReadinessCheck(
        "durable_database", not settings.is_sqlite,
        "PostgreSQL configured." if not settings.is_sqlite
        else "Using SQLite. Configure PostgreSQL (ASTRASOC_DATABASE_URL) for live mode.",
        required=False,
    ))

    # A configured (non-simulated) model provider OR AI explicitly disabled.
    providers = db.execute(
        select(ModelProvider).where(
            ModelProvider.tenant_id == tenant_id,
            ModelProvider.enabled.is_(True), ModelProvider.kind != "simulated"
        )
    ).scalars().all()
    state = get_mode(db, tenant_id)
    ai_off = (not state.ai_enabled) or state.llm_strategy in ("disabled", "simulated")
    checks.append(ReadinessCheck(
        "ai_configuration", bool(providers) or ai_off,
        f"{len(providers)} real provider(s) configured."
        if providers else
        ("AI is disabled/simulated for this tenant — the deterministic pipeline runs without an LLM."
         if ai_off else
         "No real LLM provider configured while a hosted/private strategy is selected."),
        required=False,
    ))

    return checks


def set_mode(
    db: Session,
    tenant_id: uuid.UUID,
    mode: str,
    changed_by: str,
    *,
    ai_enabled: bool | None = None,
    llm_strategy: str | None = None,
) -> ModeState:
    if mode not in ("DEMO", "LIVE"):
        raise ValueError("mode must be DEMO or LIVE")
    if mode == "LIVE" and not settings.allow_live_mode:
        raise PermissionError("Live mode is disabled for this deployment.")

    row = _get_setting(db, MODE_KEY, tenant_id)
    prev = (row.value if row else None) or (get_mode(db, tenant_id).to_dict())
    value = {
        "mode": mode,
        "changed_at": datetime.now(UTC).isoformat(),
        "changed_by": changed_by,
        "ai_enabled": prev.get("ai_enabled", True) if ai_enabled is None else ai_enabled,
        "llm_strategy": prev.get("llm_strategy", "simulated") if llm_strategy is None else llm_strategy,
        "degraded": False,
        "degraded_reasons": [],
    }
    if row is None:
        row = SystemSetting(tenant_id=tenant_id, key=MODE_KEY, value=value,
                            description="Authoritative operating mode (DEMO/LIVE).")
        db.add(row)
    else:
        row.value = value
    db.flush()
    return get_mode(db, tenant_id)


def mark_degraded(db: Session, tenant_id: uuid.UUID, reasons: list[str]) -> ModeState:
    """Record (or clear) degraded operation for a tenant; shown in the UI header."""
    row = _get_setting(db, MODE_KEY, tenant_id)
    if row is None:
        set_mode(db, tenant_id, get_mode(db, tenant_id).mode, changed_by="system")
        row = _get_setting(db, MODE_KEY, tenant_id)
    v = dict(row.value or {})
    v["degraded"] = bool(reasons)
    v["degraded_reasons"] = reasons
    row.value = v
    db.flush()
    return get_mode(db, tenant_id)
