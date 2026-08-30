"""Durable reviewer-feedback API; no automatic learning is performed."""

from fastapi import APIRouter, Depends, HTTPException

from api.schemas import FeedbackRecord, FeedbackRequest, FeedbackResponse
from data.review_store import ReviewNotFoundError, review_store
from core.security import ReviewerIdentity, authenticate_reviewer, reviewer_identity_or_local

router = APIRouter()


@router.post("/feedback", response_model=FeedbackResponse)
async def create_feedback(
    feedback: FeedbackRequest,
    reviewer: ReviewerIdentity = Depends(authenticate_reviewer),
) -> FeedbackResponse:
    identity = reviewer_identity_or_local(reviewer)
    if identity.authenticated:
        feedback = feedback.model_copy(update={"reviewer_id": identity.reviewer_id})
    elif not feedback.reviewer_id:
        raise HTTPException(status_code=422, detail="reviewer_id is required in local mode")
    try:
        feedback_id = await review_store.create_feedback(feedback, identity.allowed_tenants)
    except ReviewNotFoundError:
        raise HTTPException(status_code=404, detail="Audit request not found")
    return FeedbackResponse(
        feedback_id=feedback_id,
        recorded=True,
        message="Feedback recorded for later analysis; no policy was changed.",
    )


@router.get("/feedback/{request_id}", response_model=list[FeedbackRecord])
async def get_feedback(
    request_id: str,
    reviewer: ReviewerIdentity = Depends(authenticate_reviewer),
) -> list[FeedbackRecord]:
    identity = reviewer_identity_or_local(reviewer)
    try:
        return await review_store.get_feedback(request_id, identity.allowed_tenants)
    except ReviewNotFoundError:
        raise HTTPException(status_code=404, detail="Audit request not found")
