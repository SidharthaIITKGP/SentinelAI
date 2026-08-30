"""
SentinelAI — Async PostgreSQL Audit Logger (Gaurav's module)

Uses asyncpg for high-performance async database access.
All Pydantic models imported from api.schemas — no duplicates here.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import asyncpg

from api.schemas import (
    ActionBreakdown,
    AuditEntry,
    MetricsSummary,
    RiskDistribution,
    UseCase,
    UseCaseMetrics,
)

logger = logging.getLogger("sentinelai.audit_logger")

# ── Connection pool ────────────────────────────────────────────────────────────
_pool: Optional[asyncpg.Pool] = None

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sentinelai:sentinelai@localhost:5432/sentinelai",
)


async def _get_pool() -> asyncpg.Pool:
    """Return (or lazily create) the shared asyncpg connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("asyncpg pool created")
    return _pool


async def init_db() -> None:
    """Initialize the database pool. Called from main.py lifespan on startup."""
    await _get_pool()
    logger.info("Database pool initialized ✅")


async def close_db() -> None:
    """Close the database pool gracefully."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


# ── Helper: convert AuditEntry field to JSONB-safe value ──────────────────────

def _to_jsonb(value) -> Optional[str]:
    """Serialize a Pydantic sub-model or dict to a JSON string for JSONB storage."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump())
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, list):
        return json.dumps([
            v.model_dump() if hasattr(v, "model_dump") else v
            for v in value
        ])
    return json.dumps(value)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Public API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def log_request(audit_entry: AuditEntry) -> str:
    """
    Insert one pipeline run into audit_log.
    Returns the generated request UUID (which is audit_entry.request_id).

    Field mapping (AuditEntry → audit_log column):
      audit_entry.risk_score.overall  → risk_score    (FIX #3)
      audit_entry.action.action        → action_taken  (FIX #4)
      ActionBreakdown uses UPPERCASE fields (FIX #5)
    """
    try:
        pool = await _get_pool()

        # FIX #3: use .overall not .score
        risk_score_value = audit_entry.risk_score.overall

        # FIX #4: use .action not .action_taken
        action_taken_value = (
            audit_entry.action.action
            if isinstance(audit_entry.action.action, str)
            else audit_entry.action.action.value
        )

        risk_level_value = (
            audit_entry.risk_score.level
            if isinstance(audit_entry.risk_score.level, str)
            else audit_entry.risk_score.level.value
        )

        use_case_value = (
            audit_entry.use_case
            if isinstance(audit_entry.use_case, str)
            else audit_entry.use_case.value
        )

        # Extract flagged_claims from groundedness result
        flagged_claims = None
        if audit_entry.groundedness and audit_entry.groundedness.flagged_claims:
            flagged_claims = _to_jsonb(audit_entry.groundedness.flagged_claims)

        # Extract PII entities from pii_in_response
        pii_entities = None
        if audit_entry.pii_in_response and audit_entry.pii_in_response.found:
            pii_entities = _to_jsonb(audit_entry.pii_in_response.entities)

        # Total tokens
        tokens_used = audit_entry.tokens_total

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (
                    id, timestamp, tenant_id, use_case,
                    prompt, llm_response, final_response,
                    risk_level, risk_score, risk_breakdown,
                    action_taken, action_evidence,
                    model_used, tokens_used, latency_ms,
                    flagged_claims, pii_entities
                ) VALUES (
                    $1::uuid, $2, $3, $4,
                    $5, $6, $7,
                    $8, $9, $10::jsonb,
                    $11, $12::jsonb,
                    $13, $14, $15,
                    $16::jsonb, $17::jsonb
                )
                ON CONFLICT (id) DO NOTHING
                """,
                audit_entry.request_id,
                audit_entry.timestamp,
                audit_entry.tenant_id,
                use_case_value,
                audit_entry.prompt,
                audit_entry.llm_response,
                audit_entry.final_response,
                risk_level_value,
                risk_score_value,
                _to_jsonb(audit_entry.risk_score.breakdown),
                action_taken_value,
                _to_jsonb(audit_entry.action.evidence),
                audit_entry.model_used,
                tokens_used,
                audit_entry.latency_ms,
                flagged_claims,
                pii_entities,
            )

        logger.info(
            f"Audit log written | request_id={audit_entry.request_id} | "
            f"action={action_taken_value} | risk={risk_score_value:.2f}"
        )
        return audit_entry.request_id

    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")
        # Don't crash the pipeline — audit failure is non-fatal
        return audit_entry.request_id


def _row_to_audit_entry(row: asyncpg.Record) -> dict:
    """Convert a database row to a dict suitable for the dashboard (not full AuditEntry)."""
    return {
        "request_id": str(row["id"]),
        "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
        "tenant_id": row["tenant_id"],
        "use_case": row["use_case"],
        "prompt": row["prompt"],
        "llm_response": row["llm_response"],
        "final_response": row["final_response"],
        "risk_level": row["risk_level"],
        "risk_score": row["risk_score"],
        "risk_breakdown": json.loads(row["risk_breakdown"]) if row["risk_breakdown"] else {},
        "action_taken": row["action_taken"],
        "action_evidence": json.loads(row["action_evidence"]) if row["action_evidence"] else {},
        "model_used": row["model_used"],
        "tokens_used": row["tokens_used"],
        "latency_ms": row["latency_ms"],
        "flagged_claims": json.loads(row["flagged_claims"]) if row["flagged_claims"] else [],
        "pii_entities": json.loads(row["pii_entities"]) if row["pii_entities"] else [],
    }


async def get_recent_logs(limit: int = 50) -> List[dict]:
    """
    Return the most recent audit_log rows as dicts.
    Consumed by GET /audit/recent — dashboard LiveFeed polls every 3s.
    """
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM audit_log
                ORDER BY timestamp DESC
                LIMIT $1
                """,
                limit,
            )
        return [_row_to_audit_entry(r) for r in rows]
    except Exception as e:
        logger.error(f"get_recent_logs failed: {e}")
        return []


async def get_logs_by_use_case(use_case: str) -> List[dict]:
    """
    Return audit log rows filtered by use_case.
    """
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM audit_log
                WHERE use_case = $1
                ORDER BY timestamp DESC
                LIMIT 200
                """,
                use_case,
            )
        return [_row_to_audit_entry(r) for r in rows]
    except Exception as e:
        logger.error(f"get_logs_by_use_case failed: {e}")
        return []


async def get_metrics_summary(period: str = "24h") -> MetricsSummary:
    """
    Calculate MetricsSummary from audit_log.
    Consumed by GET /metrics — dashboard MetricsPanel polls every 30s.

    FIX #5: ActionBreakdown uses UPPERCASE field names (ALLOW, REDACT, etc.)
    """
    # Parse period
    period_hours = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}.get(period, 24)
    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(hours=period_hours)

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            # Total requests in period
            total_row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM audit_log WHERE timestamp >= $1",
                period_start,
            )
            total_requests = total_row["cnt"] if total_row else 0

            # Action breakdown — FIX #5: uses UPPERCASE field names
            action_rows = await conn.fetch(
                """
                SELECT action_taken, COUNT(*) AS cnt
                FROM audit_log
                WHERE timestamp >= $1 AND action_taken IS NOT NULL
                GROUP BY action_taken
                """,
                period_start,
            )
            action_counts = {r["action_taken"]: r["cnt"] for r in action_rows}

            # FIX #5: ActionBreakdown fields are UPPERCASE
            actions = ActionBreakdown(
                ALLOW=action_counts.get("ALLOW", 0),
                REPAIR=action_counts.get("REPAIR", 0),
                REDACT=action_counts.get("REDACT", 0),
                BLOCK=action_counts.get("BLOCK", 0),
                ESCALATE=action_counts.get("ESCALATE", 0),
                total=total_requests,
            )

            # Risk distribution
            risk_rows = await conn.fetch(
                """
                SELECT risk_level, COUNT(*) AS cnt
                FROM audit_log
                WHERE timestamp >= $1 AND risk_level IS NOT NULL
                GROUP BY risk_level
                """,
                period_start,
            )
            risk_counts = {r["risk_level"]: r["cnt"] for r in risk_rows}
            risk_distribution = RiskDistribution(
                LOW=risk_counts.get("LOW", 0),
                MEDIUM=risk_counts.get("MEDIUM", 0),
                HIGH=risk_counts.get("HIGH", 0),
                total=total_requests,
            )

            # Latency stats
            latency_row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(AVG(latency_ms), 0)                             AS avg_latency,
                    COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms), 0) AS p95_latency
                FROM audit_log
                WHERE timestamp >= $1 AND latency_ms IS NOT NULL
                """,
                period_start,
            )
            avg_latency_ms = float(latency_row["avg_latency"]) if latency_row else 0.0
            p95_latency_ms = float(latency_row["p95_latency"]) if latency_row else 0.0

            # Per-use-case breakdown
            use_case_rows = await conn.fetch(
                """
                SELECT
                    use_case,
                    COUNT(*)                     AS total,
                    COALESCE(AVG(risk_score), 0) AS avg_risk,
                    COALESCE(AVG(latency_ms), 0) AS avg_lat,
                    SUM(CASE WHEN action_taken = 'ALLOW'    THEN 1 ELSE 0 END) AS allow_cnt,
                    SUM(CASE WHEN action_taken = 'REPAIR'   THEN 1 ELSE 0 END) AS repair_cnt,
                    SUM(CASE WHEN action_taken = 'REDACT'   THEN 1 ELSE 0 END) AS redact_cnt,
                    SUM(CASE WHEN action_taken = 'BLOCK'    THEN 1 ELSE 0 END) AS block_cnt,
                    SUM(CASE WHEN action_taken = 'ESCALATE' THEN 1 ELSE 0 END) AS escalate_cnt
                FROM audit_log
                WHERE timestamp >= $1 AND use_case IS NOT NULL
                GROUP BY use_case
                """,
                period_start,
            )

            by_use_case = []
            for r in use_case_rows:
                uc_str = r["use_case"]
                # Map to UseCase enum safely
                try:
                    uc_enum = UseCase(uc_str)
                except ValueError:
                    uc_enum = UseCase.CUSTOMER_CHATBOT

                uc_total = r["total"]
                uc_metrics = UseCaseMetrics(
                    use_case=uc_enum,
                    total_requests=uc_total,
                    actions=ActionBreakdown(
                        ALLOW=r["allow_cnt"],
                        REPAIR=r["repair_cnt"],
                        REDACT=r["redact_cnt"],
                        BLOCK=r["block_cnt"],
                        ESCALATE=r["escalate_cnt"],
                        total=uc_total,
                    ),
                    avg_risk_score=float(r["avg_risk"]),
                    avg_latency_ms=float(r["avg_lat"]),
                )
                by_use_case.append(uc_metrics)

            # False positive rate from feedback table
            fp_row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE correct_action != sentinelai_action
                                     AND sentinelai_action IN ('BLOCK','REDACT','ESCALATE')) AS fp_count,
                    COUNT(*) AS total_feedback
                FROM feedback
                WHERE timestamp >= $1
                """,
                period_start,
            )
            fp_count = fp_row["fp_count"] if fp_row else 0
            total_feedback = fp_row["total_feedback"] if fp_row else 0
            false_positive_rate = (fp_count / total_feedback) if total_feedback > 0 else 0.0

            # Aggregate tallies
            pii_redaction_row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM audit_log WHERE timestamp >= $1 AND action_taken = 'REDACT'",
                period_start,
            )
            total_pii_redactions = pii_redaction_row["cnt"] if pii_redaction_row else 0

            bias_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS cnt FROM audit_log
                WHERE timestamp >= $1
                  AND risk_breakdown IS NOT NULL
                  AND (risk_breakdown->>'bias_score')::float > 0.1
                """,
                period_start,
            )
            total_bias_detections = bias_row["cnt"] if bias_row else 0

            halluc_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS cnt FROM audit_log
                WHERE timestamp >= $1
                  AND flagged_claims IS NOT NULL
                  AND jsonb_array_length(flagged_claims) > 0
                """,
                period_start,
            )
            total_hallucinations_caught = halluc_row["cnt"] if halluc_row else 0

        return MetricsSummary(
            period=period,
            period_start=period_start,
            period_end=period_end,
            total_requests=total_requests,
            actions=actions,
            risk_distribution=risk_distribution,
            avg_latency_ms=avg_latency_ms,
            p95_latency_ms=p95_latency_ms,
            false_positive_rate=false_positive_rate,
            by_use_case=by_use_case,
            total_pii_redactions=total_pii_redactions,
            total_bias_detections=total_bias_detections,
            total_hallucinations_caught=total_hallucinations_caught,
        )

    except Exception as e:
        logger.error(f"get_metrics_summary failed: {e}")
        # Return empty summary rather than crashing the dashboard
        return MetricsSummary(
            period=period,
            period_start=period_start,
            period_end=period_end,
        )
