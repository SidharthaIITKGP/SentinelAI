"""Phase 4 human-review, feedback, concurrency, and non-leakage tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import core.pipeline as pipeline
from api.routes import feedback as feedback_routes
from api.routes import intercept as intercept_routes
from api.routes import reviews as review_routes
from api.schemas import (
    ActionType,
    BiasResult,
    FeedbackRecord,
    FeedbackRequest,
    GroundednessResult,
    GroundednessVerdict,
    InjectionResult,
    InterceptRequest,
    PIIResult,
    PolicyDecision,
    RiskLevel,
    ReviewDecisionRequest,
    ReviewMetrics,
    ReviewRecord,
    ReviewStatus,
    ReviewSummary,
)
from data.review_store import ReviewConflictError, ReviewNotFoundError
from engines.efficiency.model_router import load_model_registry, route_model

NOW = datetime.now(timezone.utc)
SECRET = "held model response: account 4242"
HOLDING = "SentinelAI is holding this response for human review."


def review_record(request_id="req-1", status="PENDING", use_case="finance_tool"):
    return ReviewRecord(
        review_id=f"review-{request_id}", request_id=request_id, tenant_id="tenant-a",
        use_case=use_case, status=status, sentinelai_action="ESCALATE",
        original_response=SECRET, holding_response=HOLDING, risk_level="HIGH",
        risk_score=0.91,
        action_evidence={"policy": {"reason": "high risk"}, "routing_failure": True},
        groundedness_evidence={"detector_status": "AVAILABLE", "confidence": 0.4},
        efficiency_evidence={"selected_model": "economy", "tokens_total": 0},
        created_at=NOW,
    )


class MemoryStore:
    def __init__(self, records=()):
        self.records = {r.request_id: r for r in records}
        self.feedback = []
        self.audits = {"audit-1"}
        self.enqueued = []
        self.lock = asyncio.Lock()

    async def enqueue(self, audit):
        if audit.request_id not in {item.request_id for item in self.enqueued}:
            self.enqueued.append(audit)

    async def list(self, status, use_case, limit, allowed_tenants=None):
        status = status.value if hasattr(status, "value") else status
        rows = [r for r in self.records.values() if r.status == status]
        if use_case:
            rows = [r for r in rows if r.use_case == use_case]
        if allowed_tenants is not None:
            rows = [r for r in rows if r.tenant_id in allowed_tenants]
        rows.sort(key=lambda r: (r.created_at, r.review_id))
        return [ReviewSummary(**r.model_dump(exclude={
            "original_response", "action_evidence", "groundedness_evidence",
            "efficiency_evidence", "reviewer_id", "reviewer_notes", "edited_response",
        })) for r in rows[:limit]]

    async def get(self, request_id, allowed_tenants=None):
        if request_id not in self.records:
            raise ReviewNotFoundError(request_id)
        record = self.records[request_id]
        if allowed_tenants is not None and record.tenant_id not in allowed_tenants:
            raise ReviewNotFoundError(request_id)
        return record

    async def decide(self, request_id, decision, allowed_tenants=None):
        async with self.lock:
            record = await self.get(request_id, allowed_tenants)
            if record.status != "PENDING":
                raise ReviewConflictError(request_id)
            status = {"APPROVE": "APPROVED", "EDIT": "EDITED", "REJECT": "REJECTED"}[decision.decision]
            correct = {"APPROVE": "ALLOW", "EDIT": "REPAIR", "REJECT": "ESCALATE"}[decision.decision]
            updated = record.model_copy(update={
                "status": status, "reviewer_id": decision.reviewer_id,
                "reviewer_notes": decision.notes,
                "edited_response": decision.edited_response if status == "EDITED" else None,
                "reviewed_at": NOW,
            })
            self.records[request_id] = updated
            self.feedback.append((request_id, record.review_id, correct))
            return updated

    async def metrics(self, allowed_tenants=None):
        rows = [r for r in self.records.values() if allowed_tenants is None or r.tenant_id in allowed_tenants]
        counts = {s: sum(r.status == s for r in rows) for s in ("PENDING", "APPROVED", "EDITED", "REJECTED")}
        total = len(rows)
        completed = total - counts["PENDING"]
        return ReviewMetrics(
            total_reviews=total, pending_reviews=counts["PENDING"],
            completed_reviews=completed, approved_count=counts["APPROVED"],
            edited_count=counts["EDITED"], rejected_count=counts["REJECTED"],
            completion_rate=completed / total if total else 0,
            override_rate=counts["APPROVED"] / completed if completed else 0,
            agreement_rate=(counts["EDITED"] + counts["REJECTED"]) / completed if completed else 0,
        )

    async def create_feedback(self, item, allowed_tenants=None):
        if item.request_id not in self.audits:
            raise ReviewNotFoundError(item.request_id)
        self.feedback.append(item)
        return "feedback-1"

    async def get_feedback(self, request_id, allowed_tenants=None):
        if request_id not in self.audits:
            raise ReviewNotFoundError(request_id)
        return [FeedbackRecord(
            feedback_id="feedback-1", request_id=request_id,
            sentinelai_action="ESCALATE", correct_action="ALLOW",
            reviewer_id="reviewer", created_at=NOW,
        )]


@pytest.fixture
def store(monkeypatch):
    value = MemoryStore([review_record()])
    monkeypatch.setattr(review_routes, "review_store", value)
    monkeypatch.setattr(feedback_routes, "review_store", value)
    return value


def audit_stub(action):
    action_result = SimpleNamespace(
        action=action, final_response=SECRET if action == "ALLOW" else HOLDING,
        original_response=SECRET, evidence={"reason": "test"},
        escalation_required=action == "ESCALATE",
    )
    breakdown = SimpleNamespace(
        injection_score=0.0, pii_prompt_score=0.0, pii_response_score=0.0,
        groundedness_risk=0.8, bias_score=0.0, dominant_signal="groundedness",
    )
    audit = SimpleNamespace(
        request_id="audit-intercept", risk_score=SimpleNamespace(
            overall=0.9, level="HIGH", breakdown=breakdown),
        latency_ms=12, efficiency=None,
    )
    return action_result, audit


@pytest.mark.asyncio
@pytest.mark.parametrize("action,expected", [
    ("ESCALATE", 1), ("ALLOW", 0), ("REDACT", 0), ("REPAIR", 0), ("BLOCK", 0),
])
async def test_intercept_only_enqueues_escalations(monkeypatch, action, expected):
    store = MemoryStore()
    monkeypatch.setattr(intercept_routes, "review_store", store)
    monkeypatch.setattr(intercept_routes, "run_pipeline", AsyncMock(return_value=audit_stub(action)))
    monkeypatch.setattr(intercept_routes, "log_request", AsyncMock(return_value="audit-intercept"))
    response = await intercept_routes.intercept(InterceptRequest(
        prompt="test", use_case="finance_tool", tenant_id="t", user_id="u"))
    assert len(store.enqueued) == expected
    assert response.final_response == (SECRET if action == "ALLOW" else HOLDING)


@pytest.mark.asyncio
async def test_duplicate_escalation_enqueue_is_idempotent(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(intercept_routes, "review_store", store)
    monkeypatch.setattr(intercept_routes, "run_pipeline", AsyncMock(return_value=audit_stub("ESCALATE")))
    monkeypatch.setattr(intercept_routes, "log_request", AsyncMock(return_value="audit-intercept"))
    request = InterceptRequest(prompt="test", use_case="finance_tool", tenant_id="t", user_id="u")
    await intercept_routes.intercept(request)
    await intercept_routes.intercept(request)
    assert len(store.enqueued) == 1


@pytest.mark.asyncio
async def test_enqueue_failure_keeps_safe_holding_response(monkeypatch):
    failing = MemoryStore()
    failing.enqueue = AsyncMock(side_effect=RuntimeError("database down"))
    monkeypatch.setattr(intercept_routes, "review_store", failing)
    monkeypatch.setattr(intercept_routes, "run_pipeline", AsyncMock(return_value=audit_stub("ESCALATE")))
    monkeypatch.setattr(intercept_routes, "log_request", AsyncMock(return_value="audit-intercept"))
    response = await intercept_routes.intercept(InterceptRequest(
        prompt="test", use_case="finance_tool", tenant_id="t", user_id="u"))
    assert response.final_response == HOLDING
    assert SECRET not in response.final_response


@pytest.mark.asyncio
async def test_hard_routing_failure_skips_llm_and_enters_review_queue(monkeypatch):
    profiles, _, _ = load_model_registry()
    profiles = [profile.model_copy(deep=True) for profile in profiles]
    for profile in profiles:
        profile.enabled = profile.id == "economy"

    async def clean_injection(prompt):
        return InjectionResult(detected=False)

    async def clean_pii(text, scan_target="prompt"):
        return PIIResult(found=False, scan_target=scan_target)

    async def clean_bias(text):
        return BiasResult(detected=False)

    async def allow_policy(**kwargs):
        return PolicyDecision(
            approved=True, final_action="ALLOW", reason="clean",
            policy_file="tests/policy", threshold_applied=0.2)

    def unsafe_route(risk, use_case, prompt, *, latency_budget_ms=None):
        return route_model(RiskLevel.HIGH, "finance_tool", prompt, profiles=profiles)

    llm = AsyncMock(return_value=("must not be generated", 9, 9))
    monkeypatch.setattr(pipeline, "injection_scan", clean_injection)
    monkeypatch.setattr(pipeline, "detect_pii", clean_pii)
    monkeypatch.setattr(pipeline, "detect_bias", clean_bias)
    monkeypatch.setattr(pipeline, "scan_toxic_content", None)
    monkeypatch.setattr(pipeline, "groundedness_check", AsyncMock(return_value=GroundednessResult(
        verdict=GroundednessVerdict.SUPPORTED, score=1.0,
        total_claims_checked=1, grounded_claims_count=1,
        use_case_kb_used="finance_tool")))
    monkeypatch.setattr(pipeline, "evaluate_policy", allow_policy)
    monkeypatch.setattr(pipeline, "_classify_risk", lambda **kwargs: RiskLevel.HIGH)
    monkeypatch.setattr(pipeline, "route_model", unsafe_route)
    monkeypatch.setattr(pipeline, "_call_llm", llm)
    monkeypatch.setattr(intercept_routes, "run_pipeline", pipeline.run_pipeline)
    monkeypatch.setattr(intercept_routes, "log_request", AsyncMock(return_value="hard-route"))
    store = MemoryStore()
    monkeypatch.setattr(intercept_routes, "review_store", store)

    response = await intercept_routes.intercept(InterceptRequest(
        prompt="Approve this finance decision", use_case="finance_tool",
        tenant_id="tenant-a", user_id="user-a"))

    llm.assert_not_called()
    assert response.action_taken == "ESCALATE"
    assert "must not be generated" not in response.final_response
    assert len(store.enqueued) == 1
    assert store.enqueued[0].tokens_total == 0
    assert store.enqueued[0].action.evidence["routing_failure"] is True


@pytest.mark.asyncio
async def test_list_defaults_to_pending_and_excludes_original(store):
    store.records["req-2"] = review_record("req-2", "APPROVED")
    rows = await review_routes.list_reviews(limit=50)
    assert [row.request_id for row in rows] == ["req-1"]
    assert "original_response" not in rows[0].model_dump()


@pytest.mark.asyncio
async def test_list_filters_use_case_and_limit(monkeypatch):
    records = [review_record("a", use_case="finance_tool"), review_record("b", use_case="hr_copilot")]
    store = MemoryStore(records)
    monkeypatch.setattr(review_routes, "review_store", store)
    rows = await review_routes.list_reviews(use_case="hr_copilot", limit=1)
    assert [row.request_id for row in rows] == ["b"]


@pytest.mark.asyncio
async def test_internal_detail_contains_review_evidence(store):
    detail = await review_routes.get_review("req-1")
    assert detail.original_response == SECRET
    assert detail.groundedness_evidence["detector_status"] == "AVAILABLE"
    assert detail.efficiency_evidence["tokens_total"] == 0


@pytest.mark.asyncio
async def test_missing_review_is_404(store):
    with pytest.raises(HTTPException) as error:
        await review_routes.get_review("missing")
    assert error.value.status_code == 404


@pytest.mark.parametrize("content", [None, "", "  "])
def test_edit_requires_non_blank_content(content):
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(decision="EDIT", reviewer_id="r", edited_response=content)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision,status", [
    ("APPROVE", "APPROVED"), ("EDIT", "EDITED"), ("REJECT", "REJECTED"),
])
async def test_decision_transitions(store, decision, status):
    request = ReviewDecisionRequest(
        decision=decision, reviewer_id="reviewer-1",
        edited_response="safe edited answer" if decision == "EDIT" else None,
    )
    result = await review_routes.decide_review("req-1", request)
    assert result.status == status
    assert result.reviewer_id == "reviewer-1"
    assert len(store.feedback) == 1


@pytest.mark.asyncio
async def test_second_decision_returns_conflict(store):
    request = ReviewDecisionRequest(decision="APPROVE", reviewer_id="r")
    await review_routes.decide_review("req-1", request)
    with pytest.raises(HTTPException) as error:
        await review_routes.decide_review("req-1", request)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_decisions_one_success_one_conflict(store):
    async def decide(value):
        try:
            return await review_routes.decide_review(
                "req-1", ReviewDecisionRequest(decision=value, reviewer_id=value))
        except HTTPException as exc:
            return exc
    outcomes = await asyncio.gather(decide("APPROVE"), decide("REJECT"))
    assert sorted(getattr(item, "status_code", 200) for item in outcomes) == [200, 409]
    assert len(store.feedback) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [
    ("PENDING", HOLDING), ("APPROVED", SECRET),
    ("EDITED", "reviewer safe edit"), ("REJECTED", review_routes.REJECTED_RESPONSE),
])
async def test_resolution_state_machine(monkeypatch, status, expected):
    record = review_record(status=status).model_copy(update={"edited_response": "reviewer safe edit"})
    monkeypatch.setattr(review_routes, "review_store", MemoryStore([record]))
    result = await review_routes.get_resolution("req-1")
    assert result.response == expected
    if status in {"PENDING", "REJECTED"}:
        assert SECRET not in result.response


@pytest.mark.asyncio
async def test_empty_metrics_are_zero_safe(monkeypatch):
    monkeypatch.setattr(review_routes, "review_store", MemoryStore())
    metrics = await review_routes.review_metrics()
    assert metrics.total_reviews == metrics.completed_reviews == 0
    assert metrics.completion_rate == metrics.override_rate == metrics.agreement_rate == 0


@pytest.mark.asyncio
async def test_mixed_metrics_use_defined_formulas(monkeypatch):
    records = [review_record("p"), review_record("a", "APPROVED"), review_record("e", "EDITED"), review_record("r", "REJECTED")]
    monkeypatch.setattr(review_routes, "review_store", MemoryStore(records))
    metrics = await review_routes.review_metrics()
    assert (metrics.total_reviews, metrics.completed_reviews, metrics.pending_reviews) == (4, 3, 1)
    assert metrics.completion_rate == pytest.approx(0.75)
    assert metrics.override_rate == pytest.approx(1 / 3)
    assert metrics.agreement_rate == pytest.approx(2 / 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision,correct", [
    ("APPROVE", "ALLOW"), ("EDIT", "REPAIR"), ("REJECT", "ESCALATE"),
])
async def test_human_decision_feedback_mapping(store, decision, correct):
    await review_routes.decide_review("req-1", ReviewDecisionRequest(
        decision=decision, reviewer_id="r", edited_response="edit" if decision == "EDIT" else None))
    assert store.feedback[0][2] == correct


@pytest.mark.asyncio
async def test_feedback_persists_without_policy_learning(store):
    response = await feedback_routes.create_feedback(FeedbackRequest(
        request_id="audit-1", sentinelai_action="ESCALATE", correct_action="ALLOW",
        reviewer_id="r", notes="safe"))
    assert response.recorded is True
    assert "no policy was changed" in response.message


@pytest.mark.asyncio
async def test_feedback_rejects_unknown_audit(store):
    with pytest.raises(HTTPException) as error:
        await feedback_routes.create_feedback(FeedbackRequest(
            request_id="unknown", sentinelai_action="BLOCK", correct_action="ALLOW",
            reviewer_id="r"))
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_feedback_can_be_read_for_known_audit(store):
    rows = await feedback_routes.get_feedback("audit-1")
    assert rows[0].request_id == "audit-1"


def test_database_schema_has_idempotency_indexes_and_evidence():
    schema = Path("data/schema.sql").read_text()
    assert "request_id              UUID        NOT NULL UNIQUE" in schema
    assert "idx_feedback_review_once" in schema
    assert "groundedness_evidence" in schema and "efficiency_evidence" in schema
    assert all(name in schema for name in (
        "idx_human_reviews_status", "idx_human_reviews_created_at",
        "idx_human_reviews_tenant_id", "idx_human_reviews_use_case"))


def test_application_registers_review_feedback_and_resolution_routes():
    from core.main import app
    paths = {route.path for route in app.routes}
    assert {"/reviews", "/reviews/metrics", "/reviews/{request_id}",
            "/reviews/{request_id}/decision", "/reviews/{request_id}/resolution",
            "/feedback", "/feedback/{request_id}"} <= paths
