from fastapi import APIRouter
from api.schemas import InterceptRequest, InterceptResponse
from core.pipeline import run_pipeline
from data.audit_logger import log_request

router = APIRouter()

@router.post("/intercept", response_model=InterceptResponse)
async def intercept(request: InterceptRequest):
    # Run the pipeline
    action_result, audit_entry = await run_pipeline(request)
    
    # Log the request
    await log_request(audit_entry)
    
    # Construct and return response
    return InterceptResponse(
        request_id=audit_entry.request_id,
        final_response=action_result.final_response,
        action_taken=action_result.action_taken,
        risk_level=audit_entry.risk_score.level,
        risk_score=audit_entry.risk_score.score,
        latency_ms=audit_entry.latency_ms,
        evidence=action_result.evidence or {},
        governed=True,
        escalation_required=audit_entry.escalation_required
    )
