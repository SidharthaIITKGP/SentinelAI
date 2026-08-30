"""Phase 1 governance correctness regressions without external services."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from pydantic import ValidationError

import api.routes.intercept as intercept_route
import core.action_layer as action_layer
import core.pipeline as pipeline
import engines.responsibility.bias_detector as bias_wrapper
import engines.responsibility.pii_detector as pii_wrapper
import engines.responsibility.pii_check.policy.engine as configured_policy
import policy.engine as policy_wrapper
from api.schemas import (
    ActionResult,
    ActionType,
    BiasResult,
    DetectorStatus,
    GroundednessResult,
    GroundednessVerdict,
    InjectionResult,
    InterceptRequest,
    PIIEntity,
    PIIEntityType,
    PIIResult,
    PolicyDecision,
    RiskBreakdown,
    RiskLevel,
    RiskScore,
    UseCase,
)
from core.risk_scorer import compute
from core.risk_thresholds import risk_level_value


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _risk(score: float, use_case: UseCase = UseCase.CUSTOMER_CHATBOT) -> RiskScore:
    return RiskScore(
        overall=score,
        level=RiskLevel(risk_level_value(score)),
        breakdown=RiskBreakdown(dominant_signal="none"),
        use_case=use_case,
    )


def _policy(action: ActionType) -> PolicyDecision:
    return PolicyDecision(
        approved=action == ActionType.ALLOW,
        final_action=action,
        reason="phase 1 test decision",
        policy_file="tests/policy",
        threshold_applied=0.0,
    )


def _pii_entity(text: str, raw_value: str, entity_type: PIIEntityType) -> PIIEntity:
    start = text.index(raw_value)
    return PIIEntity(
        entity_type=entity_type,
        text=f"<{entity_type.value}>",
        start=start,
        end=start + len(raw_value),
        score=0.95,
        redacted_placeholder=f"<{entity_type.value}>",
    )


def _pii_result(text: str, raw_value: str, entity_type: PIIEntityType) -> PIIResult:
    entity = _pii_entity(text, raw_value, entity_type)
    return PIIResult(
        found=True,
        entities=[entity],
        risk_score=0.95,
        high_risk_entities=(
            [entity_type.value] if entity_type == PIIEntityType.US_SSN else []
        ),
        scan_target="response",
    )


def test_allow_returns_original_response_unchanged() -> None:
    original = "The approved answer."
    result = asyncio.run(
        action_layer.execute(
            _policy(ActionType.ALLOW),
            _risk(0.10),
            original,
            PIIResult(found=False, scan_target="response"),
            UseCase.CUSTOMER_CHATBOT,
        )
    )
    assert result.action == ActionType.ALLOW
    assert result.final_response == original


def test_block_never_returns_original_response() -> None:
    original = "Sensitive unsafe output"
    result = asyncio.run(
        action_layer.execute(
            _policy(ActionType.BLOCK),
            _risk(0.80),
            original,
            PIIResult(found=False, scan_target="response"),
            UseCase.FINANCE_TOOL,
        )
    )
    assert result.action == ActionType.BLOCK
    assert result.final_response != original
    assert original not in result.final_response


@pytest.mark.parametrize(
    ("original", "raw_value", "entity_type", "placeholder"),
    [
        (
            "Contact alex@example.com for help.",
            "alex@example.com",
            PIIEntityType.EMAIL_ADDRESS,
            "<EMAIL_ADDRESS>",
        ),
        (
            "The employee SSN is 123-45-6789.",
            "123-45-6789",
            PIIEntityType.US_SSN,
            "<US_SSN>",
        ),
    ],
)
def test_redact_removes_actual_sensitive_substrings(
    monkeypatch, original, raw_value, entity_type, placeholder
) -> None:
    pii_result = _pii_result(original, raw_value, entity_type)

    async def fake_redact(text: str):
        assert text == original
        return pii_result, text.replace(raw_value, placeholder)

    monkeypatch.setattr(action_layer, "redact_pii", fake_redact)
    result = asyncio.run(
        action_layer.execute(
            _policy(ActionType.REDACT),
            _risk(0.40),
            original,
            pii_result,
            UseCase.CUSTOMER_CHATBOT,
        )
    )
    assert result.action == ActionType.REDACT
    assert raw_value not in result.final_response
    assert placeholder in result.final_response
    assert raw_value not in str(result.evidence)


def test_redaction_failure_holds_original_pii(monkeypatch) -> None:
    original = "Contact alex@example.com for help."
    pii_result = _pii_result(
        original, "alex@example.com", PIIEntityType.EMAIL_ADDRESS
    )

    async def failed_redact(text: str):
        return (
            PIIResult(
                found=False,
                status=DetectorStatus.UNAVAILABLE,
                scan_target="response",
            ),
            text,
        )

    monkeypatch.setattr(action_layer, "redact_pii", failed_redact)
    result = asyncio.run(
        action_layer.execute(
            _policy(ActionType.REDACT),
            _risk(0.40),
            original,
            pii_result,
            UseCase.CUSTOMER_CHATBOT,
        )
    )
    assert result.action == ActionType.ESCALATE
    assert result.escalation_required is True
    assert "alex@example.com" not in result.final_response
    assert result.final_response != original


def test_escalate_holds_original_response() -> None:
    original = "Do not release this regulated recommendation."
    result = asyncio.run(
        action_layer.execute(
            _policy(ActionType.ESCALATE),
            _risk(0.50, UseCase.HR_COPILOT),
            original,
            PIIResult(found=False, scan_target="response"),
            UseCase.HR_COPILOT,
        )
    )
    assert result.action == ActionType.ESCALATE
    assert result.escalation_required is True
    assert result.final_response != original
    assert original not in result.final_response


def test_escalate_schema_rejects_original_as_final_output() -> None:
    with pytest.raises(ValidationError, match="must hold"):
        ActionResult(
            action=ActionType.ESCALATE,
            final_response="private response",
            original_response="private response",
            explanation="review",
            escalation_required=True,
        )


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.20, RiskLevel.LOW),
        (0.200001, RiskLevel.MEDIUM),
        (0.55, RiskLevel.MEDIUM),
        (0.550001, RiskLevel.HIGH),
    ],
)
def test_exact_risk_level_boundaries(score: float, expected: RiskLevel) -> None:
    assert risk_level_value(score) == expected.value
    assert _risk(score).level == expected


def test_risk_schema_rejects_a_conflicting_level() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        RiskScore(
            overall=0.55,
            level=RiskLevel.HIGH,
            breakdown=RiskBreakdown(),
            use_case=UseCase.CUSTOMER_CHATBOT,
        )


@pytest.mark.parametrize(
    ("use_case", "score", "expected"),
    [
        (UseCase.CUSTOMER_CHATBOT, 0.10, ActionType.ALLOW),
        (UseCase.HR_COPILOT, 0.40, ActionType.ESCALATE),
        (UseCase.FINANCE_TOOL, 0.80, ActionType.ESCALATE),
    ],
)
def test_policy_exception_uses_risk_aware_fallback(
    monkeypatch, use_case, score, expected
) -> None:
    def unavailable_engine():
        raise RuntimeError("test outage")

    monkeypatch.setattr(configured_policy, "get_policy_engine", unavailable_engine)
    decision = asyncio.run(
        policy_wrapper.evaluate_policy(use_case, _risk(score, use_case))
    )
    assert decision.final_action == expected
    assert "Policy evaluation was unavailable" in decision.reason
    assert decision.policy_file == "policy/fail_safe_fallback"
    if use_case in {UseCase.HR_COPILOT, UseCase.FINANCE_TOOL}:
        assert decision.final_action != ActionType.ALLOW


def test_policy_exception_never_allows_explicit_pii(monkeypatch) -> None:
    def unavailable_engine():
        raise RuntimeError("test outage")

    monkeypatch.setattr(configured_policy, "get_policy_engine", unavailable_engine)
    decision = asyncio.run(
        policy_wrapper.evaluate_policy(
            UseCase.CUSTOMER_CHATBOT,
            _risk(0.10),
            pii_detected=True,
        )
    )
    assert decision.final_action == ActionType.REDACT


def test_low_risk_customer_unavailable_check_is_labeled_degraded() -> None:
    decision = asyncio.run(
        policy_wrapper.evaluate_policy(
            UseCase.CUSTOMER_CHATBOT,
            _risk(0.10),
            unavailable_detectors=["groundedness"],
        )
    )
    assert decision.final_action == ActionType.ALLOW
    assert decision.policy_file == "policy/availability_guard"
    assert "Degraded ALLOW" in decision.reason


def test_regulated_redaction_is_held_when_another_check_is_unavailable() -> None:
    decision = asyncio.run(
        policy_wrapper.evaluate_policy(
            UseCase.HR_COPILOT,
            _risk(0.10, UseCase.HR_COPILOT),
            pii_detected=True,
            unavailable_detectors=["bias"],
        )
    )
    assert decision.final_action == ActionType.ESCALATE
    assert decision.policy_file == "policy/availability_guard"


@pytest.mark.anyio
async def test_detector_exceptions_return_unavailable(monkeypatch) -> None:
    class FailingExecutorLoop:
        def run_in_executor(self, executor, function):
            raise RuntimeError("executor unavailable")

    monkeypatch.setattr(
        pii_wrapper.asyncio,
        "get_event_loop",
        lambda: FailingExecutorLoop(),
    )

    fake_pii_module = types.ModuleType(
        "engines.responsibility.pii_check.pii_detector"
    )
    fake_pii_module.ENTITY_RISK_SCORES = {}
    fake_pii_module.get_pii_detector = lambda: (_ for _ in ()).throw(
        RuntimeError("offline")
    )
    monkeypatch.setitem(
        sys.modules,
        "engines.responsibility.pii_check.pii_detector",
        fake_pii_module,
    )
    pii_result = await pii_wrapper.detect_pii("safe-looking text")
    assert pii_result.status == DetectorStatus.UNAVAILABLE
    assert pii_result.found is False

    fake_bias_module = types.ModuleType(
        "engines.responsibility.bias_check.bias_detector"
    )
    fake_bias_module.get_bias_detector = lambda: (_ for _ in ()).throw(
        RuntimeError("offline")
    )
    monkeypatch.setitem(
        sys.modules,
        "engines.responsibility.bias_check.bias_detector",
        fake_bias_module,
    )
    bias_result = await bias_wrapper.detect_bias("safe-looking text")
    assert bias_result.status == DetectorStatus.UNAVAILABLE
    assert bias_result.detected is False


def test_groundedness_unavailable_is_not_fully_verified_and_adds_risk() -> None:
    unavailable = pipeline._mock_groundedness_result(UseCase.FINANCE_TOOL)
    assert unavailable.status == DetectorStatus.UNAVAILABLE
    assert unavailable.score == 0.0
    assert unavailable.total_claims_checked == 0

    clean_pii = PIIResult(found=False)
    risk = compute(
        injection=InjectionResult(detected=False),
        pii_prompt=clean_pii,
        groundedness=unavailable,
        pii_response=PIIResult(found=False, scan_target="response"),
        bias=BiasResult(detected=False),
        use_case=UseCase.FINANCE_TOOL,
    )
    assert risk.breakdown.groundedness_risk == 0.70
    assert risk.overall > 0.0

    with pytest.raises(ValidationError, match="must use score 0.0"):
        GroundednessResult(
            status=DetectorStatus.UNAVAILABLE,
            score=1.0,
            use_case_kb_used=UseCase.FINANCE_TOOL,
        )


def test_intercept_writes_exactly_one_audit_entry(monkeypatch) -> None:
    async def clean_injection(prompt: str):
        return InjectionResult(detected=False)

    async def clean_pii(text: str, scan_target: str = "prompt"):
        return PIIResult(found=False, scan_target=scan_target)

    async def clean_bias(text: str):
        return BiasResult(detected=False)

    async def verified_groundedness(response: str, use_case: UseCase):
        return GroundednessResult(
            verdict=GroundednessVerdict.SUPPORTED,
            score=1.0,
            total_claims_checked=1,
            grounded_claims_count=1,
            use_case_kb_used=use_case,
        )

    async def fake_llm(prompt: str, model_config, use_case: str):
        return "Governed answer", 3, 2

    async def allow_policy(**kwargs):
        return _policy(ActionType.ALLOW)

    writes: list[str] = []

    async def one_audit_write(audit_entry):
        writes.append(audit_entry.request_id)
        return audit_entry.request_id

    monkeypatch.setattr(pipeline, "injection_scan", clean_injection)
    monkeypatch.setattr(pipeline, "detect_pii", clean_pii)
    monkeypatch.setattr(pipeline, "detect_bias", clean_bias)
    monkeypatch.setattr(pipeline, "scan_toxic_content", None)
    monkeypatch.setattr(pipeline, "groundedness_check", verified_groundedness)
    monkeypatch.setattr(pipeline, "_call_llm", fake_llm)
    monkeypatch.setattr(
        pipeline,
        "route_model",
        lambda *args: {
            "model": "test/model",
            "max_tokens": 10,
            "temperature": 0.0,
            "reason": "test",
        },
    )
    monkeypatch.setattr(pipeline, "evaluate_policy", allow_policy)
    monkeypatch.setattr(intercept_route, "log_request", one_audit_write)

    response = asyncio.run(
        intercept_route.intercept(
            InterceptRequest(
                prompt="What is the approved policy?",
                use_case=UseCase.CUSTOMER_CHATBOT,
                tenant_id="tenant-test",
                user_id="user-test",
            )
        )
    )

    assert response.final_response == "Governed answer"
    assert response.action_taken == ActionType.ALLOW
    assert len(writes) == 1
