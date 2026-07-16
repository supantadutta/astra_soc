"""ASTRASOC API application entrypoint."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .db import SessionLocal, init_db
from .middleware import RateLimitMiddleware, RequestIDMiddleware

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("astrasoc")

_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) Schema + baseline seed (idempotent).
    init_db()
    from .seed.bootstrap import ensure_seed
    from .seed.engine import ensure_demo_data, run_live_generator

    with SessionLocal() as db:
        tenant = ensure_seed(db)
        if settings.demo_seed_on_startup:
            ensure_demo_data(db, tenant.id)

    # 2) Continuous demo event generator (only produces DEMO-scoped data).
    if settings.environment != "test":
        task = asyncio.create_task(run_live_generator())
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
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


# --- Live event stream (SSE) ---------------------------------------------
@app.get("/api/v1/stream", tags=["system"])
async def event_stream(request: Request, scope: str = "DEMO"):
    """Server-Sent Events stream of platform activity for the given scope.

    The dashboard and module views subscribe here for real-time updates without
    polling or full-page refreshes.
    """
    from .services.events import bus

    queue = await bus.subscribe()

    async def generator():
        try:
            # Replay a little recent history so a fresh client isn't blank.
            for ev in bus.recent(scope, limit=20):
                yield ev.sse()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    if ev.scope == scope:
                        yield ev.sse()
                except TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            bus.unsubscribe(queue)

    return EventSourceResponse(generator())


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
        knowledge,
        models,
        playbooks,
        rbac,
        reports,
        response,
        system,
        threatintel,
    )

    # Primary routers.
    for module in (
        auth, system, dashboard, alerts, incidents, entities, agents, models,
        connectors, detections, threatintel, playbooks, response, knowledge,
        reports, rbac, audit_log, evaluations, demo,
    ):
        app.include_router(module.router)

    # Additional sub-routers defined alongside their primary module.
    app.include_router(detections.query_router)     # /api/v1/query
    app.include_router(response.approvals_router)    # /api/v1/approvals
    app.include_router(rbac.tenants_router)          # /api/v1/tenants
    app.include_router(dashboard.health_router)      # /api/v1/platform


register_routers()
