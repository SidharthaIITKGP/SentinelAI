from api.schemas import ActionType, PolicyEvaluationRequest, UseCase
from engines.responsibility.pii_check.policy.engine import PolicyEngine


def test_bias_signal_is_escalated_by_policy_not_detector():
    decision = PolicyEngine().evaluate(
        PolicyEvaluationRequest(
            use_case=UseCase.HR_COPILOT,
            risk_score=0.62,
            bias_detected=True,
            proposed_action=ActionType.ALLOW,
        )
    )
    assert decision.final_action == ActionType.ESCALATE
    assert "Bias detector signal" in decision.reason


def test_configured_risk_threshold_takes_precedence_over_bias_signal():
    decision = PolicyEngine().evaluate(
        PolicyEvaluationRequest(
            use_case=UseCase.FINANCE_TOOL,
            risk_score=0.70,
            bias_detected=True,
            proposed_action=ActionType.ALLOW,
        )
    )
    assert decision.final_action == ActionType.BLOCK
