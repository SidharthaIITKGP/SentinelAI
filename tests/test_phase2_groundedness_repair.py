"""Phase 2 groundedness verdict and bounded repair regressions."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

import core.action_layer as action_layer
import core.pipeline as pipeline
import engines.trust.groundedness as groundedness
from api.schemas import (
    ActionType,
    ClaimEvaluation,
    DetectorStatus,
    GroundednessResult,
    GroundednessVerdict,
    PIIResult,
    PolicyDecision,
    RiskBreakdown,
    RiskLevel,
    RiskScore,
    UseCase,
)


HR_SOURCE = {
    "score": 0.91,
    "doc_id": "hr_001",
    "title": "Paid Time Off and Leave Policy",
    "content": "Acme Corp employees receive 10 paid sick days per calendar year.",
    "use_case": "hr_copilot",
}


def _evaluation(
    verdict: GroundednessVerdict,
    claim: str = "Employees receive 20 paid sick days per year.",
) -> ClaimEvaluation:
    return ClaimEvaluation(
        claim_text=claim,
        verdict=verdict,
        similarity_score=0.91,
        source_doc_id="hr_001",
        source_title="Paid Time Off and Leave Policy",
        source_excerpt=HR_SOURCE["content"],
        reason="test evidence",
        contradiction_type=(
            "NUMERIC_MISMATCH"
            if verdict == GroundednessVerdict.CONTRADICTED
            else None
        ),
    )


def _groundedness_result(verdict: GroundednessVerdict) -> GroundednessResult:
    status = (
        DetectorStatus.UNAVAILABLE
        if verdict == GroundednessVerdict.UNAVAILABLE
        else DetectorStatus.AVAILABLE
    )
    if verdict == GroundednessVerdict.UNAVAILABLE:
        return GroundednessResult(
            status=status,
            verdict=verdict,
            score=0.0,
            use_case_kb_used=UseCase.HR_COPILOT,
        )
    score = {
        GroundednessVerdict.SUPPORTED: 1.0,
        GroundednessVerdict.INSUFFICIENT_EVIDENCE: 0.5,
        GroundednessVerdict.CONTRADICTED: 0.0,
    }[verdict]
    return GroundednessResult(
        status=status,
        verdict=verdict,
        score=score,
        claim_evaluations=[_evaluation(verdict)],
        total_claims_checked=1,
        grounded_claims_count=int(verdict == GroundednessVerdict.SUPPORTED),
        use_case_kb_used=UseCase.HR_COPILOT,
    )


def _risk(use_case: UseCase = UseCase.HR_COPILOT) -> RiskScore:
    return RiskScore(
        overall=0.45,
        level=RiskLevel.MEDIUM,
        breakdown=RiskBreakdown(groundedness_risk=1.0, dominant_signal="groundedness_risk"),
        use_case=use_case,
    )


def _repair_policy() -> PolicyDecision:
    return PolicyDecision(
        approved=False,
        final_action=ActionType.REPAIR,
        reason="contradicted claim",
        policy_file="policy/groundedness_guard",
        threshold_applied=0.5,
    )


def test_numeric_contradiction_and_support() -> None:
    contradicted = groundedness.evaluate_claim(
        "Employees receive 20 paid sick days per year.", [HR_SOURCE], 0.5
    )
    supported = groundedness.evaluate_claim(
        "Employees receive 10 paid sick days per year.", [HR_SOURCE], 0.5
    )
    assert contradicted.verdict == GroundednessVerdict.CONTRADICTED
    assert contradicted.contradiction_type == "NUMERIC_MISMATCH"
    assert contradicted.source_doc_id == "hr_001"
    assert supported.verdict == GroundednessVerdict.SUPPORTED


def test_negation_and_direction_contradictions() -> None:
    negation = groundedness.evaluate_claim(
        "Remote work is not allowed for employees.",
        [{**HR_SOURCE, "content": "Remote work is allowed for eligible employees."}],
        0.5,
    )
    direction = groundedness.evaluate_claim(
        "Quarterly revenue decreased during the period.",
        [{**HR_SOURCE, "content": "Quarterly revenue increased during the period."}],
        0.5,
    )
    may_pair = groundedness.evaluate_claim(
        "Employees may enroll in the benefit.",
        [{**HR_SOURCE, "content": "Employees may not enroll in the benefit."}],
        0.5,
    )
    assert negation.verdict == GroundednessVerdict.CONTRADICTED
    assert negation.contradiction_type == "NEGATION"
    assert direction.verdict == GroundednessVerdict.CONTRADICTED
    assert direction.contradiction_type == "CATEGORICAL"
    assert may_pair.verdict == GroundednessVerdict.CONTRADICTED


def test_low_similarity_is_insufficient_never_contradicted() -> None:
    result = groundedness.evaluate_claim(
        "Employees receive 20 paid sick days per year.",
        [{**HR_SOURCE, "score": 0.20}],
        0.5,
    )
    assert result.verdict == GroundednessVerdict.INSUFFICIENT_EVIDENCE


def test_aggregation_precedence_and_empty_behavior() -> None:
    supported = _evaluation(GroundednessVerdict.SUPPORTED)
    insufficient = _evaluation(GroundednessVerdict.INSUFFICIENT_EVIDENCE)
    contradicted = _evaluation(GroundednessVerdict.CONTRADICTED)
    assert groundedness.aggregate_verdict([supported]) == GroundednessVerdict.SUPPORTED
    assert groundedness.aggregate_verdict([supported, insufficient]) == GroundednessVerdict.INSUFFICIENT_EVIDENCE
    assert groundedness.aggregate_verdict([supported, insufficient, contradicted]) == GroundednessVerdict.CONTRADICTED
    assert groundedness.aggregate_verdict([]) == GroundednessVerdict.INSUFFICIENT_EVIDENCE


def test_retrieval_failure_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(groundedness, "_embedding_model", object())
    monkeypatch.setattr(groundedness, "_qdrant_client", object())

    async def failed_search(*args, **kwargs):
        raise groundedness.GroundednessUnavailableError("offline")

    monkeypatch.setattr(groundedness, "_embed_and_search", failed_search)
    result = asyncio.run(
        groundedness.check("Employees receive 10 paid sick days.", UseCase.HR_COPILOT)
    )
    assert result.status == DetectorStatus.UNAVAILABLE
    assert result.verdict == GroundednessVerdict.UNAVAILABLE
    assert result.score == 0.0


def test_empty_or_non_checkable_response_is_insufficient(monkeypatch) -> None:
    monkeypatch.setattr(groundedness, "_embedding_model", object())
    monkeypatch.setattr(groundedness, "_qdrant_client", object())
    result = asyncio.run(
        groundedness.check("I cannot help.", UseCase.HR_COPILOT)
    )
    assert result.verdict == GroundednessVerdict.INSUFFICIENT_EVIDENCE
    assert result.score == 0.5
    assert result.total_claims_checked == 0


def test_unavailable_status_and_verdict_must_match() -> None:
    with pytest.raises(ValidationError, match="iff"):
        GroundednessResult(
            status=DetectorStatus.AVAILABLE,
            verdict=GroundednessVerdict.UNAVAILABLE,
            score=0.0,
            use_case_kb_used=UseCase.HR_COPILOT,
        )


def test_successful_repair_uses_evidence_and_releases_supported_answer() -> None:
    calls = 0

    async def repair_once(prompt: str):
        nonlocal calls
        calls += 1
        assert "20 paid sick days" in prompt
        assert "10 paid sick days" in prompt
        assert "using only the supplied local evidence" in prompt
        return "Employees receive 10 paid sick days per year.", _groundedness_result(
            GroundednessVerdict.SUPPORTED
        )

    result = asyncio.run(
        action_layer.execute(
            _repair_policy(),
            _risk(),
            "Employees receive 20 paid sick days per year.",
            PIIResult(found=False, scan_target="response"),
            UseCase.HR_COPILOT,
            original_prompt="How many paid sick days do employees receive?",
            groundedness_result=_groundedness_result(GroundednessVerdict.CONTRADICTED),
            repair_callback=repair_once,
        )
    )
    assert calls == 1
    assert result.action == ActionType.REPAIR
    assert result.final_response == "Employees receive 10 paid sick days per year."
    assert result.repair_attempts == 1
    assert result.evidence["source_doc_ids"] == ["hr_001"]
    assert result.evidence["repair_success"] is True


@pytest.mark.parametrize(
    "after_verdict",
    [
        GroundednessVerdict.CONTRADICTED,
        GroundednessVerdict.INSUFFICIENT_EVIDENCE,
        GroundednessVerdict.UNAVAILABLE,
    ],
)
def test_failed_repair_outcomes_are_held_once(after_verdict) -> None:
    calls = 0

    async def repair_once(prompt: str):
        nonlocal calls
        calls += 1
        return "Unverified repaired content", _groundedness_result(after_verdict)

    result = asyncio.run(
        action_layer.execute(
            _repair_policy(),
            _risk(UseCase.FINANCE_TOOL),
            "Employees receive 20 paid sick days per year.",
            PIIResult(found=False, scan_target="response"),
            UseCase.FINANCE_TOOL,
            original_prompt="How many sick days?",
            groundedness_result=_groundedness_result(GroundednessVerdict.CONTRADICTED),
            repair_callback=repair_once,
        )
    )
    assert calls == 1
    assert result.action == ActionType.ESCALATE
    assert result.escalation_required is True
    assert "20 paid sick days" not in result.final_response
    assert "Unverified repaired content" not in result.final_response
    assert result.repair_attempts == 1


@pytest.mark.parametrize("use_case", [UseCase.HR_COPILOT, UseCase.FINANCE_TOOL])
def test_insufficient_regulated_evidence_escalates_without_repair(use_case) -> None:
    calls = 0

    async def should_not_run(prompt: str):
        nonlocal calls
        calls += 1
        raise AssertionError("repair must not run")

    decision = pipeline._apply_groundedness_policy_guard(
        PolicyDecision(
            approved=True,
            final_action=ActionType.ALLOW,
            reason="low aggregate risk",
            policy_file="tests/policy",
            threshold_applied=0.5,
        ),
        _groundedness_result(GroundednessVerdict.INSUFFICIENT_EVIDENCE),
        use_case,
    )
    result = asyncio.run(
        action_layer.execute(
            decision,
            _risk(use_case),
            "Unverified regulated answer",
            PIIResult(found=False, scan_target="response"),
            use_case,
            groundedness_result=_groundedness_result(
                GroundednessVerdict.INSUFFICIENT_EVIDENCE
            ),
            repair_callback=should_not_run,
        )
    )
    assert calls == 0
    assert result.action == ActionType.ESCALATE
    assert result.repair_attempts == 0
