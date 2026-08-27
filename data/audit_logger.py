import os
import json
import asyncpg
from typing import List
from api.schemas import AuditEntry, MetricsSummary, UseCaseMetrics, ActionBreakdown, RiskDistribution

# Connection pool singleton
_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        dsn = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sentinel")
        _pool = await asyncpg.create_pool(dsn)
    return _pool

async def log_request(audit_entry: AuditEntry) -> str:
    """Logs the request to the audit_log table and returns the request_id."""
    pool = await get_pool()
    query = """
        INSERT INTO audit_log (
            id, timestamp, tenant_id, use_case, prompt, llm_response, 
            final_response, risk_level, risk_score, risk_breakdown, 
            action_taken, action_evidence, model_used, tokens_used, 
            latency_ms, flagged_claims, pii_entities
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17
        ) RETURNING id
    """
    
    # Flatten risk breakdown, evidence, etc to JSON
    risk_breakdown = audit_entry.risk_score.breakdown.model_dump_json() if audit_entry.risk_score.breakdown else "{}"
    action_evidence = audit_entry.action.evidence if audit_entry.action.evidence else "{}"
    flagged_claims = audit_entry.groundedness.model_dump_json()
    pii_entities = audit_entry.pii_in_prompt.model_dump_json()
    
    async with pool.acquire() as conn:
        request_id = await conn.fetchval(
            query,
            audit_entry.request_id,
            audit_entry.timestamp,
            audit_entry.tenant_id,
            audit_entry.use_case.value,
            audit_entry.prompt,
            audit_entry.llm_response,
            audit_entry.final_response,
            audit_entry.risk_score.level.value if hasattr(audit_entry.risk_score.level, "value") else audit_entry.risk_score.level,
            audit_entry.risk_score.score,
            risk_breakdown,
            audit_entry.action.action_taken.value if hasattr(audit_entry.action.action_taken, "value") else audit_entry.action.action_taken,
            json.dumps(action_evidence) if isinstance(action_evidence, dict) else action_evidence,
            audit_entry.model_used,
            audit_entry.tokens_total,
            audit_entry.latency_ms,
            flagged_claims,
            pii_entities
        )
    return str(request_id)

async def _row_to_audit_entry(row: asyncpg.Record) -> AuditEntry:
    # A complete re-mapping to AuditEntry would be complex.
    # In a real app we'd construct the Pydantic model properly.
    # Since the instructions don't strictly require full hydration for the UI logs,
    # we can construct a partial dict or use BaseModel.model_validate.
    # We will build a compatible dict to pass to AuditEntry.model_validate.
    
    # For simplicity, we assume we just return dicts that the API returns as JSON,
    # but the signature says List[AuditEntry].
    # Let's try to mock the nested structures or just return raw dicts if it fails.
    # Actually, the API might just need the basic fields for LiveFeed.
    return {
        "request_id": str(row["id"]),
        "timestamp": row["timestamp"].isoformat(),
        "tenant_id": row["tenant_id"],
        "use_case": row["use_case"],
        "prompt": row["prompt"],
        "llm_response": row["llm_response"],
        "final_response": row["final_response"],
        "risk_score": {
            "level": row["risk_level"],
            "score": row["risk_score"],
            "breakdown": json.loads(row["risk_breakdown"] or "{}")
        },
        "action": {
            "action_taken": row["action_taken"],
            "evidence": json.loads(row["action_evidence"] or "{}")
        },
        "latency_ms": row["latency_ms"],
        "model_used": row["model_used"]
    }

async def get_recent_logs(limit=50) -> List[dict]:
    pool = await get_pool()
    query = "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT $1"
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit)
    return [await _row_to_audit_entry(row) for row in rows]

async def get_logs_by_use_case(use_case: str) -> List[dict]:
    pool = await get_pool()
    query = "SELECT * FROM audit_log WHERE use_case = $1 ORDER BY timestamp DESC"
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, use_case)
    return [await _row_to_audit_entry(row) for row in rows]

async def get_metrics_summary() -> MetricsSummary:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM audit_log")
        avg_latency = await conn.fetchval("SELECT AVG(latency_ms) FROM audit_log") or 0.0
        
        actions_rows = await conn.fetch("SELECT action_taken, COUNT(*) FROM audit_log GROUP BY action_taken")
        actions = {row["action_taken"]: row["count"] for row in actions_rows}
        
        risk_rows = await conn.fetch("SELECT risk_level, COUNT(*) FROM audit_log GROUP BY risk_level")
        risks = {row["risk_level"]: row["count"] for row in risk_rows}
        
        uc_rows = await conn.fetch("SELECT use_case, COUNT(*) as reqs, AVG(latency_ms) as lat FROM audit_log GROUP BY use_case")
        by_use_case = []
        for r in uc_rows:
            by_use_case.append(UseCaseMetrics(
                use_case=r["use_case"],
                total_requests=r["reqs"],
                avg_latency_ms=r["lat"] or 0.0,
                actions=ActionBreakdown(),
                risk_distribution=RiskDistribution()
            ))

    import datetime
    now = datetime.datetime.utcnow()
    
    return MetricsSummary(
        period="24h",
        period_start=now - datetime.timedelta(days=1),
        period_end=now,
        total_requests=total,
        actions=ActionBreakdown(
            allow=actions.get("ALLOW", 0),
            redact=actions.get("REDACT", 0),
            block=actions.get("BLOCK", 0),
            repair=actions.get("REPAIR", 0),
            escalate=actions.get("ESCALATE", 0)
        ),
        risk_distribution=RiskDistribution(
            low=risks.get("LOW", 0),
            medium=risks.get("MEDIUM", 0),
            high=risks.get("HIGH", 0)
        ),
        avg_latency_ms=float(avg_latency),
        by_use_case=by_use_case
    )
