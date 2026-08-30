"""
SentinelAI — authenticated POST /intercept route

Wires the incoming HTTP request through the existing core.pipeline.run_pipeline()
and persists the audit entry.

CRITICAL FIXES applied:
  FIX #1: use action_result.action     (not .action_taken)
  FIX #2: use audit_entry.risk_score.overall (not .score)
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from api.schemas import ActionType, InterceptRequest, InterceptResponse
from core.pipeline import run_pipeline
from core.governance_receipt import build_governance_receipt
from core.security import TenantIdentity, authenticate_tenant, tenant_identity_or_local
from data.audit_logger import log_request
from data.review_store import review_store

logger = logging.getLogger("sentinelai.intercept")

router = APIRouter()


@router.post(
    "/intercept",
    response_model=InterceptResponse,
    summary="Govern an LLM request",
    description=(
        "Intercepts an incoming LLM prompt, runs the 5-step SentinelAI "
        "governance pipeline, persists the audit entry, and returns the "
        "governed response."
    ),
)
async def intercept(
    request: InterceptRequest,
    tenant_identity: TenantIdentity = Depends(authenticate_tenant),
) -> InterceptResponse:
    """
    POST /intercept

    Flow:
      1. Receive InterceptRequest
      2. Call core.pipeline.run_pipeline() → (ActionResult, AuditEntry)
      3. Persist AuditEntry via data.audit_logger.log_request()
      4. Return InterceptResponse with request_id, action, risk info, latency
    """
    wall_start = time.time()
    identity = tenant_identity_or_local(tenant_identity)
    if identity.authenticated:
        if request.tenant_id != identity.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant identity does not match credentials")
        request = request.model_copy(update={"tenant_id": identity.tenant_id})

    try:
        # Step 2 — run the full governance pipeline
        action_result, audit_entry = await run_pipeline(request)
    except Exception as e:
        logger.error("Pipeline failed | error_type=%s", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="Governance pipeline failed")

    # Step 3 — the route owns the one durable audit write.
    try:
        request_id = await log_request(audit_entry)
    except Exception as e:
        logger.warning("Audit log failed (non-fatal) | error_type=%s", type(e).__name__)
        request_id = audit_entry.request_id

    # Escalations become durable review work. Queue failure must never release
    # held content or make the intercept endpoint fail open.
    if action_result.action == ActionType.ESCALATE.value:
        try:
            await review_store.enqueue(audit_entry)
        except Exception as e:
            logger.error(
                "Human-review enqueue failed for %s | error_type=%s",
                request_id, type(e).__name__,
            )

    # Total wall-clock latency (includes audit write)
    total_latency_ms = max(1, int((time.time() - wall_start) * 1000))

    # FIX #1: action_result.action  (not .action_taken)
    action_taken = action_result.action

    # FIX #2: audit_entry.risk_score.overall  (not .score)
    risk_score_value = audit_entry.risk_score.overall
    risk_level_value = audit_entry.risk_score.level

    # Step 4 — build and return the governed response
    return InterceptResponse(
        request_id=request_id,
        final_response=action_result.final_response,
        action_taken=action_taken,
        risk_level=risk_level_value,
        risk_score=risk_score_value,
        latency_ms=audit_entry.latency_ms or total_latency_ms,
        evidence=action_result.evidence,
        efficiency=audit_entry.efficiency,
        governance_receipt=build_governance_receipt(audit_entry, request_id),
        governed=True,
        escalation_required=action_result.escalation_required,
        risk_breakdown={
            "injection_score":    audit_entry.risk_score.breakdown.injection_score,
            "pii_prompt_score":   audit_entry.risk_score.breakdown.pii_prompt_score,
            "pii_response_score": audit_entry.risk_score.breakdown.pii_response_score,
            "groundedness_risk":  audit_entry.risk_score.breakdown.groundedness_risk,
            "bias_score":         audit_entry.risk_score.breakdown.bias_score,
            "dominant_signal":    audit_entry.risk_score.breakdown.dominant_signal,
        },
    )
