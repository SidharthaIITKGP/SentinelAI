"""Internal human-review queue and public-safe resolution endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.schemas import (
    ReviewDecisionRequest,
    ReviewMetrics,
    ReviewRecord,
    ReviewResolution,
    ReviewStatus,
    ReviewSummary,
    UseCase,
)
from data.review_store import ReviewConflictError, ReviewNotFoundError, review_store

router = APIRouter()

PENDING_RESPONSE = "This request is awaiting human review."
REJECTED_RESPONSE = "This request was not approved by human review."


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Review request not found")


@router.get("/reviews/metrics", response_model=ReviewMetrics)
async def review_metrics() -> ReviewMetrics:
    return await review_store.metrics()


@router.get("/reviews", response_model=list[ReviewSummary])
async def list_reviews(
    status: ReviewStatus = ReviewStatus.PENDING,
    use_case: Optional[UseCase] = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ReviewSummary]:
    return await review_store.list(status, use_case, limit)


@router.get("/reviews/{request_id}/resolution", response_model=ReviewResolution)
async def get_resolution(request_id: str) -> ReviewResolution:
    try:
        review = await review_store.get(request_id)
    except ReviewNotFoundError:
        raise _not_found()
    if review.status == ReviewStatus.PENDING.value:
        response = review.holding_response or PENDING_RESPONSE
    elif review.status == ReviewStatus.APPROVED.value:
        response = review.original_response
    elif review.status == ReviewStatus.EDITED.value:
        response = review.edited_response or ""
    else:
        response = REJECTED_RESPONSE
    return ReviewResolution(request_id=request_id, status=review.status, response=response)


@router.get("/reviews/{request_id}", response_model=ReviewRecord)
async def get_review(request_id: str) -> ReviewRecord:
    try:
        return await review_store.get(request_id)
    except ReviewNotFoundError:
        raise _not_found()


@router.post("/reviews/{request_id}/decision", response_model=ReviewRecord)
async def decide_review(
    request_id: str, decision: ReviewDecisionRequest
) -> ReviewRecord:
    try:
        return await review_store.decide(request_id, decision)
    except ReviewNotFoundError:
        raise _not_found()
    except ReviewConflictError:
        raise HTTPException(status_code=409, detail="Review has already been resolved")
