"""
SentinelAI — FastAPI Application Entry Point

Starts the server, registers all routes, initializes service connections on startup.
All service initialization is stubbed — real connections wired in Day 2-3.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.responsibility import router as responsibility_router
from api.schemas import HealthResponse

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


# ── Lifespan (modern replacement for deprecated @app.on_event) ─────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup initialization and graceful shutdown of all services."""

    # ── STARTUP ────────────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("SentinelAI starting up...")
    logger.info("=" * 50)

    # Step 1 — Load knowledge base (requires Qdrant)
    logger.info("[1/5] Loading knowledge base from sample_docs.json...")
    try:
        from engines.trust.groundedness import initialize_knowledge_base
        await initialize_knowledge_base(qdrant_host=QDRANT_HOST, qdrant_port=QDRANT_PORT)
        logger.info("[1/5] Knowledge base loaded ✅")
    except Exception as exc:
        logger.warning(f"[1/5] Knowledge base / Qdrant unavailable (non-fatal): {exc}")
        logger.warning("[1/5] Groundedness checks will be skipped until Qdrant is reachable.")

    # Step 2 — Initialize injection detector
    logger.info("[2/5] Initializing injection detector...")
    try:
        from core.injection_detector import init_injection_detector
        await init_injection_detector(qdrant_host=QDRANT_HOST, qdrant_port=QDRANT_PORT)
        logger.info("[2/5] Injection detector initialized ✅")
    except Exception as exc:
        logger.warning(f"[2/5] Injection detector init failed (non-fatal): {exc}")

    # Step 3 — Connect to PostgreSQL
    logger.info("[3/5] Connecting to PostgreSQL...")
    try:
        from data.audit_logger import init_db
        await init_db()
        logger.info("[3/5] PostgreSQL connected ✅")
    except Exception as exc:
        logger.warning(f"[3/5] PostgreSQL connection failed (non-fatal): {exc}")

    # Step 4 — Initialize Presidio PII analyzer
    logger.info("[4/5] Initializing Presidio PII analyzer...")
    try:
        from engines.responsibility.pii_check.pii_detector import get_pii_detector
        get_pii_detector()  # warms up Presidio singleton on startup
        logger.info("[4/5] Presidio initialized ✅")
    except Exception as exc:
        logger.warning(f"[4/5] Presidio PII analyzer init failed (non-fatal): {exc}")

    # Step 5 — Initialize Policy Engine
    logger.info("[5/5] Loading policy engine...")
    try:
        from engines.responsibility.pii_check.policy.engine import get_policy_engine
        get_policy_engine()  # warms up policy engine singleton on startup
        logger.info("[5/5] Policy engine initialized ✅")
    except Exception as exc:
        logger.warning(f"[5/5] Policy engine init failed (non-fatal): {exc}")



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
    allow_origins=["*"],        # dashboard needs this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Route registration ────────────────────────────────────────────────────────
# Wrapped in try/except so the server starts even if route files aren't built yet

app.include_router(responsibility_router)

try:
    from api.routes import intercept
    app.include_router(intercept.router, tags=["Intercept"])
    logger.info("Intercept routes registered")
except ImportError:
    logger.warning("api/routes/intercept.py not found — skipping (Gaurav builds this)")

try:
    from api.routes import metrics
    app.include_router(metrics.router, tags=["Metrics"])
    logger.info("Metrics routes registered")
except ImportError:
    logger.warning("api/routes/metrics.py not found — skipping (Gaurav builds this)")

try:
    from api.routes import feedback
    app.include_router(feedback.router, tags=["Feedback"])
    logger.info("Feedback routes registered")
except ImportError:
    logger.warning("api/routes/feedback.py not found — skipping (Sidhartha builds this)")


# ── Health check endpoint ──────────────────────────────────────────────────────
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check",
    description="Returns the current health status of SentinelAI and all dependent services.",
)
async def health_check():
    """
    Health check endpoint.
    Returns status of all dependent services.
    Services show False until real connections are wired in Day 2-3.
    """
    uptime = time.time() - START_TIME

    # TODO Day 2-3: replace False with actual connectivity checks
    # e.g. qdrant_healthy = await check_qdrant_connection()

    return HealthResponse(
        status="ok",
        services={
            "qdrant": False,       # TODO: wire real check Day 2
            "postgres": False,     # TODO: wire real check Day 3
            "redis": False,        # TODO: wire real check Day 3
            "opa": False,          # TODO: wire real check Day 3 — Aman's module
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
