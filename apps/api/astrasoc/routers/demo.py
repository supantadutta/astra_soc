"""Demo Control Center API: scenarios, launch/reset/reseed, generator control."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.context import Principal
from ..auth.deps import require_permission
from ..db import get_db
from ..schemas.common import serialize
from ..seed.engine import (
    generator_state,
    launch_scenario,
    reset_demo,
    set_generator,
)
from ..seed.scenarios import SCENARIOS
from ..services import audit
from ..services.mode import get_mode

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


@router.get("/scenarios")
def list_scenarios(principal: Principal = Depends(require_permission("demo:manage"))) -> dict:
    return {"scenarios": [
        {"key": s["key"], "title": s["title"], "severity": s["severity"],
         "business_risk": s["business_risk"], "attack_tactics": s["attack_tactics"],
         "attack_techniques": s["attack_techniques"], "summary": s["summary"]}
        for s in SCENARIOS]}


@router.post("/scenarios/{scenario_key}/launch")
def launch(scenario_key: str,
           principal: Principal = Depends(require_permission("demo:manage")),
           db: Session = Depends(get_db)) -> dict:
    """Create a fresh incident from a scenario. DEMO mode only."""
    if get_mode(db).is_live:
        raise HTTPException(400, detail="Scenario launch is only available in DEMO mode.")
    try:
        inc = launch_scenario(db, principal.tenant_id, scenario_key)
    except KeyError:
        raise HTTPException(404, detail="Unknown scenario")
    audit.record(db, action="demo.scenario_launched", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="incident",
                 resource_id=str(inc.id), data_scope="DEMO", detail={"scenario": scenario_key})
    db.commit()
    return serialize(inc)


@router.post("/reset")
def reset(principal: Principal = Depends(require_permission("demo:manage")),
          db: Session = Depends(get_db)) -> dict:
    """Delete all DEMO-scoped data for the tenant and reseed. LIVE data is never
    touched."""
    if get_mode(db).is_live:
        raise HTTPException(400, detail="Cannot reset demo data while in LIVE mode.")
    result = reset_demo(db, principal.tenant_id)
    audit.record(db, action="demo.reset", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, data_scope="DEMO", detail=result)
    db.commit()
    return result


@router.get("/generator")
def get_generator(principal: Principal = Depends(require_permission("demo:manage"))) -> dict:
    return generator_state()


@router.post("/generator")
def control_generator(payload: dict,
                      principal: Principal = Depends(require_permission("demo:manage"))) -> dict:
    """Pause/resume/speed the synthetic event generator."""
    return set_generator(paused=payload.get("paused"), speed=payload.get("speed"))
