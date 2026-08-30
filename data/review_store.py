"""PostgreSQL-backed human-review and feedback state.

Review transitions live here so API handlers cannot accidentally implement a
select-then-update race.  The audit log remains immutable after interception.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from api.schemas import (
    ActionType,
    AuditEntry,
    FeedbackRecord,
    FeedbackRequest,
    ReviewDecision,
    ReviewDecisionRequest,
    ReviewMetrics,
    ReviewRecord,
    ReviewStatus,
    ReviewSummary,
)
from data.audit_logger import _get_pool, _to_jsonb


class ReviewNotFoundError(Exception):
    pass


class ReviewConflictError(Exception):
    pass


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value


def _record(row: Any) -> ReviewRecord:
    return ReviewRecord(
        review_id=str(row["id"]),
        request_id=str(row["request_id"]),
        tenant_id=row["tenant_id"],
        use_case=row["use_case"],
        status=row["status"],
        sentinelai_action=row["sentinelai_action"],
        original_response=row["original_response"] or "",
        holding_response=row["holding_response"],
        risk_level=row["risk_level"],
        risk_score=float(row["risk_score"]),
        action_evidence=_json(row["action_evidence"]) or {},
        groundedness_evidence=_json(row["groundedness_evidence"]),
        efficiency_evidence=_json(row["efficiency_evidence"]),
        reviewer_id=row["reviewer_id"],
        reviewer_notes=row["reviewer_notes"],
        edited_response=row["edited_response"],
        created_at=row["created_at"],
        reviewed_at=row["reviewed_at"],
    )


def _summary(record: ReviewRecord) -> ReviewSummary:
    return ReviewSummary(**record.model_dump(exclude={
        "original_response", "action_evidence", "groundedness_evidence",
        "efficiency_evidence", "reviewer_id", "reviewer_notes", "edited_response",
    }))


class PostgresReviewStore:
    async def enqueue(self, audit: AuditEntry) -> Optional[ReviewRecord]:
        """Idempotently enqueue an escalated audit item."""
        action = audit.action.action.value if hasattr(audit.action.action, "value") else audit.action.action
        if action != ActionType.ESCALATE.value:
            return None
        use_case = audit.use_case.value if hasattr(audit.use_case, "value") else audit.use_case
        risk_level = audit.risk_score.level.value if hasattr(audit.risk_score.level, "value") else audit.risk_score.level
        action_evidence = {
            "action": audit.action.model_dump(
                mode="json", exclude={"original_response", "final_response"}
            ),
            "policy": audit.policy_decision.model_dump(mode="json"),
        }
        pool = await _get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO human_reviews (
                request_id, tenant_id, use_case, status, sentinelai_action,
                original_response, holding_response, risk_level, risk_score,
                action_evidence, groundedness_evidence, efficiency_evidence
            ) VALUES ($1,$2,$3,'PENDING',$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11::jsonb)
            ON CONFLICT (request_id) DO NOTHING
            RETURNING *
            """,
            audit.request_id, audit.tenant_id, use_case, action,
            audit.action.original_response or "", audit.action.final_response,
            risk_level, audit.risk_score.overall, _to_jsonb(action_evidence),
            _to_jsonb(audit.groundedness), _to_jsonb(audit.efficiency),
        )
        if row is None:
            row = await pool.fetchrow(
                "SELECT * FROM human_reviews WHERE request_id = $1", audit.request_id
            )
        return _record(row) if row else None

    async def list(
        self, status: ReviewStatus, use_case: Optional[str], limit: int,
        allowed_tenants: Optional[tuple[str, ...]] = None,
    ) -> list[ReviewSummary]:
        pool = await _get_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM human_reviews
            WHERE status = $1 AND ($2::varchar IS NULL OR use_case = $2)
              AND ($3::varchar[] IS NULL OR tenant_id = ANY($3::varchar[]))
            ORDER BY created_at ASC, id ASC
            LIMIT $4
            """,
            status.value if hasattr(status, "value") else status,
            use_case,
            list(allowed_tenants) if allowed_tenants is not None else None,
            limit,
        )
        return [_summary(_record(row)) for row in rows]

    async def get(
        self, request_id: str, allowed_tenants: Optional[tuple[str, ...]] = None
    ) -> ReviewRecord:
        pool = await _get_pool()
        row = await pool.fetchrow(
            """SELECT * FROM human_reviews WHERE request_id = $1
               AND ($2::varchar[] IS NULL OR tenant_id = ANY($2::varchar[]))""",
            request_id,
            list(allowed_tenants) if allowed_tenants is not None else None,
        )
        if row is None:
            raise ReviewNotFoundError(request_id)
        return _record(row)

    async def decide(
        self, request_id: str, decision: ReviewDecisionRequest,
        allowed_tenants: Optional[tuple[str, ...]] = None,
    ) -> ReviewRecord:
        status_by_decision = {
            ReviewDecision.APPROVE.value: ReviewStatus.APPROVED.value,
            ReviewDecision.EDIT.value: ReviewStatus.EDITED.value,
            ReviewDecision.REJECT.value: ReviewStatus.REJECTED.value,
        }
        correct_action = {
            ReviewDecision.APPROVE.value: ActionType.ALLOW.value,
            ReviewDecision.EDIT.value: ActionType.REPAIR.value,
            ReviewDecision.REJECT.value: ActionType.ESCALATE.value,
        }[decision.decision]
        pool = await _get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    UPDATE human_reviews
                    SET status=$2, reviewer_id=$3, reviewer_notes=$4,
                        edited_response=$5, reviewed_at=NOW()
                    WHERE request_id=$1 AND status='PENDING'
                      AND ($6::varchar[] IS NULL OR tenant_id = ANY($6::varchar[]))
                    RETURNING *
                    """,
                    request_id, status_by_decision[decision.decision],
                    decision.reviewer_id, decision.notes,
                    decision.edited_response if decision.decision == ReviewDecision.EDIT.value else None,
                    list(allowed_tenants) if allowed_tenants is not None else None,
                )
                if row is None:
                    exists = await conn.fetchval(
                        """SELECT EXISTS(SELECT 1 FROM human_reviews WHERE request_id=$1
                           AND ($2::varchar[] IS NULL OR tenant_id = ANY($2::varchar[])))""",
                        request_id,
                        list(allowed_tenants) if allowed_tenants is not None else None,
                    )
                    if not exists:
                        raise ReviewNotFoundError(request_id)
                    raise ReviewConflictError(request_id)
                await conn.execute(
                    """
                    INSERT INTO feedback (
                        request_id, review_id, sentinelai_action, correct_action,
                        reviewer_id, notes, false_positive, false_negative
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (review_id) DO NOTHING
                    """,
                    request_id, row["id"], row["sentinelai_action"], correct_action,
                    decision.reviewer_id, decision.notes,
                    correct_action == ActionType.ALLOW.value,
                    False,
                )
        return _record(row)

    async def metrics(
        self, allowed_tenants: Optional[tuple[str, ...]] = None
    ) -> ReviewMetrics:
        pool = await _get_pool()
        row = await pool.fetchrow(
            """
            SELECT COUNT(*) AS total,
              COUNT(*) FILTER (WHERE status='PENDING') AS pending,
              COUNT(*) FILTER (WHERE status='APPROVED') AS approved,
              COUNT(*) FILTER (WHERE status='EDITED') AS edited,
              COUNT(*) FILTER (WHERE status='REJECTED') AS rejected
            FROM human_reviews
            WHERE ($1::varchar[] IS NULL OR tenant_id = ANY($1::varchar[]))
            """,
            list(allowed_tenants) if allowed_tenants is not None else None,
        )
        counts = {key: int(row[key] or 0) for key in ("total", "pending", "approved", "edited", "rejected")}
        completed = counts["approved"] + counts["edited"] + counts["rejected"]
        return ReviewMetrics(
            total_reviews=counts["total"], pending_reviews=counts["pending"],
            completed_reviews=completed, approved_count=counts["approved"],
            edited_count=counts["edited"], rejected_count=counts["rejected"],
            completion_rate=completed / counts["total"] if counts["total"] else 0.0,
            override_rate=counts["approved"] / completed if completed else 0.0,
            agreement_rate=(counts["edited"] + counts["rejected"]) / completed if completed else 0.0,
        )

    async def create_feedback(
        self, feedback: FeedbackRequest,
        allowed_tenants: Optional[tuple[str, ...]] = None,
    ) -> str:
        pool = await _get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO feedback (
                request_id, sentinelai_action, correct_action, reviewer_id,
                notes, false_positive, false_negative
            )
            SELECT id,$2,$3,$4,$5,$6,$7 FROM audit_log WHERE id=$1
              AND ($8::varchar[] IS NULL OR tenant_id = ANY($8::varchar[]))
            RETURNING id
            """,
            feedback.request_id, feedback.sentinelai_action, feedback.correct_action,
            feedback.reviewer_id, feedback.notes, feedback.false_positive,
            feedback.false_negative,
            list(allowed_tenants) if allowed_tenants is not None else None,
        )
        if row is None:
            raise ReviewNotFoundError(feedback.request_id)
        return str(row["id"])

    async def get_feedback(
        self, request_id: str, allowed_tenants: Optional[tuple[str, ...]] = None
    ) -> list[FeedbackRecord]:
        pool = await _get_pool()
        rows = await pool.fetch(
            """SELECT f.* FROM feedback f
               JOIN audit_log a ON a.id=f.request_id
               WHERE f.request_id=$1
                 AND ($2::varchar[] IS NULL OR a.tenant_id = ANY($2::varchar[]))
               ORDER BY f.timestamp ASC, f.id ASC""",
            request_id,
            list(allowed_tenants) if allowed_tenants is not None else None,
        )
        if not rows:
            exists = await pool.fetchval(
                """SELECT EXISTS(SELECT 1 FROM audit_log WHERE id=$1
                   AND ($2::varchar[] IS NULL OR tenant_id = ANY($2::varchar[])))""",
                request_id,
                list(allowed_tenants) if allowed_tenants is not None else None,
            )
            if not exists:
                raise ReviewNotFoundError(request_id)
        return [FeedbackRecord(
            feedback_id=str(row["id"]), request_id=str(row["request_id"]),
            sentinelai_action=row["sentinelai_action"], correct_action=row["correct_action"],
            reviewer_id=row["reviewer_id"], notes=row["notes"],
            false_positive=bool(row["false_positive"]), false_negative=bool(row["false_negative"]),
            created_at=row["timestamp"],
        ) for row in rows]


review_store = PostgresReviewStore()
