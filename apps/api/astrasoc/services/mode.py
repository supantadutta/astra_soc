"""Backend-enforced DEMO / LIVE operating mode.

The operating mode is a *server-side* state stored in ``SystemSetting`` — not a
frontend toggle. Everything downstream reads it:

* Data queries filter by ``data_scope`` matching the current mode, so demo and
  live rows never mix.
* The response gateway refuses to send production-changing actions while in
  DEMO mode; in DEMO every action is simulated and clearly labelled.
* Switching DEMO -> LIVE requires the ``mode:manage`` permission, an explicit
  confirmation, and passing readiness checks.
"""
from __future__ import annotations

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


def _get_setting(db: Session, key: str) -> SystemSetting | None:
    return db.execute(
        select(SystemSetting).where(SystemSetting.tenant_id.is_(None), SystemSetting.key == key)
    ).scalar_one_or_none()


def get_mode(db: Session) -> ModeState:
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


def current_scope(db: Session) -> str:
    """The ``data_scope`` value the current mode operates on."""
    return "LIVE" if get_mode(db).is_live else "DEMO"


@dataclass
class ReadinessCheck:
    name: str
    passed: bool
    detail: str
    required: bool = True


def live_readiness(db: Session) -> list[ReadinessCheck]:
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
        select(Connector).where(Connector.enabled.is_(True), Connector.use_mock.is_(False))
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
            ModelProvider.enabled.is_(True), ModelProvider.kind != "simulated"
        )
    ).scalars().all()
    checks.append(ReadinessCheck(
        "ai_configuration", True,
        f"{len(providers)} real provider(s) configured."
        if providers else
        "No real LLM provider — live mode will run with AI in simulated/disabled fallback.",
        required=False,
    ))

    return checks


def set_mode(
    db: Session,
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

    row = _get_setting(db, MODE_KEY)
    prev = row.value if row else {}
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
        row = SystemSetting(tenant_id=None, key=MODE_KEY, value=value,
                            description="Authoritative operating mode (DEMO/LIVE).")
        db.add(row)
    else:
        row.value = value
    db.flush()
    return get_mode(db)


def mark_degraded(db: Session, reasons: list[str]) -> ModeState:
    """Return to safe degraded operation if critical dependencies fail."""
    row = _get_setting(db, MODE_KEY)
    if row is None:
        return get_mode(db)
    v = dict(row.value or {})
    v["degraded"] = bool(reasons)
    v["degraded_reasons"] = reasons
    row.value = v
    db.flush()
    return get_mode(db)
