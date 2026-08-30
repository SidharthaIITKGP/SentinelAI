"""
SentinelAI — FastAPI Application Entry Point

Starts the server, registers routes, validates configuration, and initializes
the dependencies used by the executable prototype.
"""

from __future__ import annotations

import logging
import os
import time
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import feedback, intercept, metrics, reviews
from api.routes.responsibility import router as responsibility_router
from api.schemas import HealthResponse
from core import health
from core.config import load_runtime_config, validate_runtime_config

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger("sentinelai")

# ── Startup timer ──────────────────────────────────────────────────────────────
START_TIME = time.time()
RUNTIME_CONFIG = load_runtime_config()


def warn_for_raw_audit_mode(audit_content_mode: str) -> None:
    if audit_content_mode == "raw":
        logger.warning("Raw audit content storage is enabled.")


# ── Lifespan (modern replacement for deprecated @app.on_event) ─────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup initialization and graceful shutdown of all services."""

    # ── STARTUP ────────────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("SentinelAI starting up...")
    logger.info("=" * 50)

    config = validate_runtime_config()
    warn_for_raw_audit_mode(config.audit_content_mode)

    # Step 1 — Load knowledge base (requires Qdrant)
    logger.info("[1/5] Loading knowledge base from sample_docs.json...")
    try:
        from engines.trust.groundedness import initialize_knowledge_base
        await initialize_knowledge_base(qdrant_host=QDRANT_HOST, qdrant_port=QDRANT_PORT)
        logger.info("[1/5] Knowledge base loaded ✅")
    except Exception as exc:
        logger.warning("[1/5] Knowledge base / Qdrant unavailable (non-fatal): %s", type(exc).__name__)
        logger.warning("[1/5] Groundedness checks will be skipped until Qdrant is reachable.")

    # Step 2 — Initialize injection detector
    logger.info("[2/5] Initializing injection detector...")
    try:
        from core.injection_detector import init_injection_detector
        await init_injection_detector(qdrant_host=QDRANT_HOST, qdrant_port=QDRANT_PORT)
        logger.info("[2/5] Injection detector initialized ✅")
    except Exception as exc:
        logger.warning("[2/5] Injection detector init failed (non-fatal): %s", type(exc).__name__)

    # Step 3 — Connect to PostgreSQL
    logger.info("[3/5] Connecting to PostgreSQL...")
    try:
        from data.audit_logger import init_db
        await init_db()
        logger.info("[3/5] PostgreSQL connected ✅")
    except Exception as exc:
        logger.warning("[3/5] PostgreSQL connection failed (non-fatal): %s", type(exc).__name__)

    # Step 4 — Initialize Presidio PII analyzer
    logger.info("[4/5] Initializing Presidio PII analyzer...")
    try:
        from engines.responsibility.pii_check.pii_detector import get_pii_detector
        get_pii_detector()  # warms up Presidio singleton on startup
        logger.info("[4/5] Presidio initialized ✅")
    except Exception as exc:
        logger.warning("[4/5] Presidio PII analyzer init failed (non-fatal): %s", type(exc).__name__)

    # Step 5 — Initialize Policy Engine
    logger.info("[5/5] Loading policy engine...")
    try:
        from engines.responsibility.pii_check.policy.engine import get_policy_engine
        get_policy_engine()  # warms up policy engine singleton on startup
        logger.info("[5/5] Policy engine initialized ✅")
    except Exception as exc:
        logger.warning("[5/5] Policy engine init failed (non-fatal): %s", type(exc).__name__)



    logger.info("=" * 50)
    logger.info("SentinelAI startup complete. Server ready.")
    logger.info("=" * 50)

    yield  # server runs here

    # ── SHUTDOWN ───────────────────────────────────────────────────────────
    logger.info("SentinelAI shutting down...")
    try:
        from data.audit_logger import close_db
        await close_db()
    except Exception:
        pass
    logger.info("Shutdown complete.")


# ── FastAPI app instance ───────────────────────────────────────────────────────
app = FastAPI(
    title="SentinelAI",
    description=(
        "Real-time AI governance control plane. Intercepts LLM requests and "
        "responses, evaluates trust/responsibility/efficiency, and takes "
        "governed actions before delivery."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── CORS middleware ────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(RUNTIME_CONFIG.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Content-Type", "Authorization", "X-Sentinel-API-Key",
        "X-Sentinel-Reviewer-Key",
    ],
)


# ── Route registration ────────────────────────────────────────────────────────
app.include_router(responsibility_router)
app.include_router(intercept.router, tags=["Intercept"])
app.include_router(metrics.router, tags=["Metrics"])
app.include_router(feedback.router, tags=["Feedback"])
app.include_router(reviews.router, tags=["Human Review"])


# ── Health check endpoint ──────────────────────────────────────────────────────
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check",
    description="Returns the current health status of SentinelAI and all dependent services.",
)
async def health_check():
    """Report live dependency checks without performing an LLM generation."""
    uptime = time.time() - START_TIME

    postgres_ok, qdrant_ok = await asyncio.gather(
        health.check_postgresql(), health.check_qdrant()
    )
    llm_configured = health.llm_is_configured()
    if postgres_ok and qdrant_ok and llm_configured:
        status = "ok"
    elif not postgres_ok and not qdrant_ok and not llm_configured:
        status = "unhealthy"
    else:
        status = "degraded"

    return HealthResponse(
        status=status,
        services={
            "api": True,
            "postgresql": postgres_ok,
            "qdrant": qdrant_ok,
            "llm_configured": llm_configured,
        },
        version="1.0.0",
        uptime_seconds=round(uptime, 2),
    )


# ── Root endpoint ──────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    """Root endpoint — basic server info and navigation links."""
    return {
        "name": "SentinelAI",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }
