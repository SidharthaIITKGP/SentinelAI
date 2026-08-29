"""
SentinelAI — GET /metrics route (Gaurav's module)

Returns aggregated MetricsSummary from the audit_log table.
Dashboard MetricsPanel polls this every 30 seconds.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from api.schemas import MetricsSummary
from data.audit_logger import get_metrics_summary, get_recent_logs

logger = logging.getLogger("sentinelai.metrics")

router = APIRouter()


@router.get(
    "/metrics",
    response_model=MetricsSummary,
    summary="Get aggregated metrics",
    description=(
        "Returns aggregated governance metrics (action breakdown, risk distribution, "
        "latency stats, per-use-case breakdown) for the specified time period. "
        "Dashboard MetricsPanel polls this every 30 seconds."
    ),
)
async def get_metrics(
    period: str = Query(
        default="24h",
        description="Time period: 1h | 24h | 7d | 30d",
        pattern="^(1h|24h|7d|30d)$",
    ),
) -> MetricsSummary:
    """GET /metrics?period=24h"""
    summary = await get_metrics_summary(period=period)
    return summary


@router.get(
    "/audit/recent",
    summary="Get recent audit log entries",
    description=(
        "Returns the most recent audit log entries. "
        "LiveFeed polls every 3 seconds. AuditLog also calls this."
    ),
)
async def get_audit_recent(
    limit: int = Query(default=20, ge=1, le=200),
) -> list:
    """GET /audit/recent?limit=20"""
    logs = await get_recent_logs(limit=limit)
    return logs
