"""Phase 4 policy tests: deterministic decisions from safe aggregate inputs."""

import pytest

from api.schemas import ActionType, PolicyEvaluationRequest, UseCase
from engines.responsibility.pii_check.policy.engine import PolicyConfigurationError, PolicyEngine


@pytest.mark.parametrize(
    ("use_case", "risk_score", "expected_action", "expected_threshold"),
    [
        (UseCase.CUSTOMER_CHATBOT, 0.75, ActionType.BLOCK, 0.75),
        (UseCase.HR_COPILOT, 0.75, ActionType.ESCALATE, 0.75),
        (UseCase.FINANCE_TOOL, 0.70, ActionType.BLOCK, 0.70),
    ],
)
def test_risk_boundaries_are_use_case_specific(
    use_case, risk_score, expected_action, expected_threshold
) -> None:
    decision = PolicyEngine().evaluate(
        PolicyEvaluationRequest(use_case=use_case, risk_score=risk_score, proposed_action=expected_action)
    )
    assert decision.final_action == expected_action
    assert decision.approved is True
    assert decision.threshold_applied == expected_threshold


def test_high_risk_overrides_sensitive_data_redaction() -> None:
    decision = PolicyEngine().evaluate(
        PolicyEvaluationRequest(
            use_case=UseCase.FINANCE_TOOL,
            risk_score=0.95,
            pii_detected=True,
            proposed_action=ActionType.REDACT,
        )
    )
    assert decision.final_action == ActionType.BLOCK
    assert decision.approved is False


@pytest.mark.parametrize("signal", ["pii_detected", "secrets_detected"])
def test_sensitive_data_requires_redaction(signal: str) -> None:
    request = PolicyEvaluationRequest(use_case=UseCase.CUSTOMER_CHATBOT, risk_score=0.2)
    setattr(request, signal, True)
    decision = PolicyEngine().evaluate(request)
    assert decision.final_action == ActionType.REDACT
    assert decision.threshold_applied == 0.0


def test_confidential_information_requires_escalation() -> None:
    decision = PolicyEngine().evaluate(
        PolicyEvaluationRequest(
            use_case=UseCase.HR_COPILOT,
            risk_score=0.2,
            confidential_detected=True,
            proposed_action=ActionType.ESCALATE,
        )
    )
    assert decision.final_action == ActionType.ESCALATE
    assert decision.approved is True


def test_safe_request_is_allowed() -> None:
    decision = PolicyEngine().evaluate(
        PolicyEvaluationRequest(use_case=UseCase.CUSTOMER_CHATBOT, risk_score=0.0)
    )
    assert decision.final_action == ActionType.ALLOW
    assert decision.approved is True
    assert decision.policy_file == "engines/responsibility/pii_check/policy/thresholds.yaml"


def test_invalid_policy_is_rejected(tmp_path) -> None:
    policy_file = tmp_path / "bad-policy.yaml"
    policy_file.write_text("use_cases:\n  customer_chatbot:\n    block_at: 0.2\n    escalate_at: 0.8\n")
    with pytest.raises(PolicyConfigurationError):
        PolicyEngine(policy_file)
