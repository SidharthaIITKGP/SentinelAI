from fastapi import APIRouter, Query
from api.schemas import MetricsSummary
from data.audit_logger import get_metrics_summary

router = APIRouter()

@router.get("/metrics", response_model=MetricsSummary)
async def metrics(period: str = Query("24h")):
    """
    Returns metrics summary.
    The period parameter is currently accepted but defaults to 24h.
    """
    summary = await get_metrics_summary()
    return summary

@router.get("/audit/recent")
async def recent_logs(limit: int = Query(20)):
    from data.audit_logger import get_recent_logs
    return await get_recent_logs(limit=limit)
