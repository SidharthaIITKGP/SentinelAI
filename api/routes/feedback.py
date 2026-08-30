"""Durable reviewer-feedback API; no automatic learning is performed."""

from fastapi import APIRouter, HTTPException

from api.schemas import FeedbackRecord, FeedbackRequest, FeedbackResponse
from data.review_store import ReviewNotFoundError, review_store

router = APIRouter()


@router.post("/feedback", response_model=FeedbackResponse)
async def create_feedback(feedback: FeedbackRequest) -> FeedbackResponse:
    try:
        feedback_id = await review_store.create_feedback(feedback)
    except ReviewNotFoundError:
        raise HTTPException(status_code=404, detail="Audit request not found")
    return FeedbackResponse(
        feedback_id=feedback_id,
        recorded=True,
        message="Feedback recorded for later analysis; no policy was changed.",
    )


@router.get("/feedback/{request_id}", response_model=list[FeedbackRecord])
async def get_feedback(request_id: str) -> list[FeedbackRecord]:
    try:
        return await review_store.get_feedback(request_id)
    except ReviewNotFoundError:
        raise HTTPException(status_code=404, detail="Audit request not found")
