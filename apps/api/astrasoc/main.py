"""ASTRASOC API application entrypoint."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import production_problems, settings
from .db import SessionLocal, init_db
from .middleware import RateLimitMiddleware, RequestIDMiddleware, SecurityHeadersMiddleware

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("astrasoc")

_background_tasks: set[asyncio.Task] = set()


async def run_sla_sweeper(interval: float = 60.0) -> None:
    """Record SLA breaches and escalate, once a minute."""
    from .services.sla import sweep_breaches

    def _tick() -> int:
        with SessionLocal() as db:
            n = sweep_breaches(db)
            db.commit()
            return n

    while True:
        try:
            n = await asyncio.to_thread(_tick)
            if n:
                logger.info("SLA sweeper escalated %d incident(s)", n)
        except Exception:  # noqa: BLE001 — log and keep the worker alive
            logger.exception("SLA sweeper failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 0) Deliver events published from worker threads on this loop.
    from .services.events import bus

    bus.bind_loop(asyncio.get_running_loop())

    # 1) Refuse unsafe production configuration, then schema + baseline seed.
    if settings.is_production:
        problems = production_problems(settings)
        if problems:
            for p in problems:
                logger.critical("Refusing to start: %s", p)
            raise RuntimeError("Unsafe production configuration: " + " | ".join(problems))
    init_db()
    from .seed.bootstrap import ensure_seed
    from .seed.engine import ensure_demo_estate_data, run_live_generator

    with SessionLocal() as db:
        ensure_seed(db)
        if settings.demo_seed_on_startup and settings.should_seed_demo_users:
            ensure_demo_estate_data(db)

    # 2) Background workers: SLA breach sweeper (always) and the continuous
    #    demo event generator (only produces DEMO-scoped data).
    if settings.environment != "test":
        workers = [run_sla_sweeper()]
        if settings.should_seed_demo_users:
            workers.append(run_live_generator())
        for coro in workers:
            task = asyncio.create_task(coro)
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    logger.info("ASTRASOC API ready (environment=%s, db=%s)",
                settings.environment, "sqlite" if settings.is_sqlite else "postgres")
    yield

    for task in _background_tasks:
        task.cancel()


app = FastAPI(
    title="ASTRASOC API",
    description="Autonomous Security Operations & Cognitive Response Platform. "
                "All trust-bearing controls (mode, RBAC, policy, response authorization, "
                "audit) are enforced server-side; LLMs are advisory only.",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["authorization", "content-type", "x-api-key", "x-tenant-id", "x-request-id"],
    expose_headers=["x-request-id", "x-response-time-ms"],
)


# --- Standardized error envelope -----------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        body = {"request_id": getattr(request.state, "request_id", None), **detail}
        body.setdefault("error", "error")
        body.setdefault("message", "")
    else:
        body = {
            "error": "http_error",
            "message": str(detail),
            "request_id": getattr(request.state, "request_id", None),
        }
    return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "Request failed validation.",
            "request_id": getattr(request.state, "request_id", None),
            "detail": exc.errors(),
        },
    )


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "astrasoc-api", "version": "0.1.0"}


@app.get("/", tags=["system"])
async def root():
    return {
        "name": "ASTRASOC",
        "description": "Autonomous Security Operations & Cognitive Response Platform",
        "docs": "/api/docs",
        "health": "/health",
    }


def register_routers() -> None:
    from .routers import (
        agents,
        alerts,
        audit_log,
        auth,
        connectors,
        dashboard,
        demo,
        detections,
        entities,
        evaluations,
        incidents,
        ingest,
        knowledge,
        models,
        mssp,
        notifications,
        playbooks,
        rbac,
        reports,
        response,
        stream,
        system,
        threatintel,
    )

    # Primary routers.
    for module in (
        auth, system, dashboard, alerts, incidents, entities, agents, models,
        connectors, detections, threatintel, playbooks, response, knowledge,
        reports, rbac, audit_log, evaluations, demo, mssp, notifications, stream, ingest,
    ):
        app.include_router(module.router)

    # Additional sub-routers defined alongside their primary module.
    app.include_router(detections.query_router)     # /api/v1/query
    app.include_router(response.approvals_router)    # /api/v1/approvals
    app.include_router(rbac.tenants_router)          # /api/v1/tenants
    app.include_router(dashboard.health_router)      # /api/v1/platform


register_routers()
