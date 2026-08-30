"""
SentinelAI — Policy Engine Wrapper

Thin wrapper around Aman's PolicyEngine.
Exposes the async interface that core/pipeline.py expects.

Aman's actual implementation is at:
  engines/responsibility/pii_check/policy/engine.py

This wrapper provides:
  evaluate_policy(use_case, risk_score) -> PolicyDecision
"""
from __future__ import annotations

import logging
from typing import Iterable

from api.schemas import (
    ActionType,
    PolicyDecision,
    PolicyEvaluationRequest,
    RiskScore,
    UseCase,
)

logger = logging.getLogger("sentinelai")


def fallback_policy_decision(
    use_case: UseCase,
    risk_score: RiskScore,
    *,
    pii_detected: bool = False,
    bias_detected: bool = False,
    secrets_detected: bool = False,
    injection_detected: bool = False,
    unavailable_detectors: Iterable[str] = (),
) -> PolicyDecision:
    """Apply a small, deterministic fail-safe policy when evaluation is unavailable."""
    use_case_key = str(getattr(use_case, "value", use_case))
    unavailable = sorted(set(unavailable_detectors))
    regulated = use_case_key in {"hr_copilot", "finance_tool"}

    if injection_detected or secrets_detected:
        action = ActionType.BLOCK
        rule = "explicit_injection_or_secret_block"
    elif risk_score.level == "HIGH":
        action = ActionType.ESCALATE if regulated else ActionType.BLOCK
        rule = "high_risk_fail_safe"
    elif bias_detected:
        action = ActionType.ESCALATE
        rule = "explicit_bias_hold"
    elif pii_detected:
        action = ActionType.REDACT
        rule = "explicit_pii_redact"
    elif regulated and (risk_score.level == "MEDIUM" or unavailable):
        action = ActionType.ESCALATE
        rule = "regulated_unknown_or_medium_hold"
    elif regulated:
        action = ActionType.ESCALATE
        rule = "regulated_policy_unavailable_hold"
    elif risk_score.level == "MEDIUM":
        action = ActionType.ESCALATE
        rule = "customer_medium_risk_hold"
    else:
        action = ActionType.ALLOW
        rule = "customer_low_risk_degraded_allow"

    detector_note = f" Unavailable checks: {', '.join(unavailable)}." if unavailable else ""
    return PolicyDecision(
        approved=action == ActionType.ALLOW,
        final_action=action,
        reason=(
            "Policy evaluation was unavailable; applied local fail-safe rule "
            f"'{rule}'.{detector_note}"
        ),
        policy_file="policy/fail_safe_fallback",
        threshold_applied=0.0,
        policy_rule_ids=[f"fallback.{rule}"],
    )


async def evaluate_policy(
    use_case: UseCase,
    risk_score: RiskScore,
    pii_detected: bool = False,
    bias_detected: bool = False,
    secrets_detected: bool = False,
    injection_detected: bool = False,
    unavailable_detectors: Iterable[str] = (),
) -> PolicyDecision:
    """
    Evaluate policy for a given use case and risk score.
    Called in Step 5 ACT+LOG after risk scoring.

    Delegates to Aman's deterministic PolicyEngine which reads
    thresholds from engines/responsibility/pii_check/policy/thresholds.yaml

    Args:
        use_case:         Which use case policy to apply
        risk_score:       Combined RiskScore from risk_scorer.py
        pii_detected:     Whether PII was found in the response
        bias_detected:    Whether bias was detected in the response
        secrets_detected: Whether secrets/credentials were detected

    Returns:
        PolicyDecision with final_action, reason, threshold_applied
    """
    try:
        from engines.responsibility.pii_check.policy.engine import get_policy_engine

        use_case_str = (
            use_case.value if hasattr(use_case, "value") else use_case
        )

        request = PolicyEvaluationRequest(
            use_case=use_case_str,
            risk_score=risk_score.overall,
            proposed_action=ActionType.ALLOW,
            pii_detected=pii_detected,
            bias_detected=bias_detected,
            secrets_detected=secrets_detected,
        )

        decision = get_policy_engine().evaluate(request)

        unavailable = sorted(set(unavailable_detectors))
        use_case_key = str(getattr(use_case, "value", use_case))
        if (
            unavailable
            and use_case_key in {"hr_copilot", "finance_tool"}
            and decision.final_action not in {ActionType.BLOCK, ActionType.ESCALATE}
        ):
            logger.warning(
                "Regulated request held because critical checks were unavailable: %s",
                ", ".join(unavailable),
            )
            return PolicyDecision(
                approved=False,
                final_action=ActionType.ESCALATE,
                reason=(
                    "Configured policy would allow, but critical detector checks were "
                    "unavailable in a regulated use case. Mandatory review is required."
                ),
                policy_file="policy/availability_guard",
                threshold_applied=0.0,
                policy_rule_ids=["availability.regulated_critical_check"],
            )
        if (
            unavailable
            and use_case_key == "customer_chatbot"
            and decision.final_action == ActionType.ALLOW
        ):
            if risk_score.level != "LOW":
                return PolicyDecision(
                    approved=False,
                    final_action=ActionType.ESCALATE,
                    reason=(
                        "Detector checks were unavailable and aggregate risk was not LOW. "
                        "The response is held for human review."
                    ),
                    policy_file="policy/availability_guard",
                    threshold_applied=0.0,
                    policy_rule_ids=["availability.customer_unknown_hold"],
                )
            return PolicyDecision(
                approved=True,
                final_action=ActionType.ALLOW,
                reason=(
                    "Degraded ALLOW for LOW-risk customer traffic: configured policy "
                    f"evaluated successfully, but checks were unavailable ({', '.join(unavailable)})."
                ),
                policy_file="policy/availability_guard",
                threshold_applied=0.0,
                policy_rule_ids=["availability.customer_low_degraded_allow"],
            )

        logger.info(
            f"Policy evaluated | use_case={use_case_str} | "
            f"risk={risk_score.overall:.3f} | "
            f"action={decision.final_action} | "
            f"reason={decision.reason}"
        )
        return decision

    except Exception as exc:
        logger.error("Policy evaluator unavailable: %s", type(exc).__name__)
        return fallback_policy_decision(
            use_case,
            risk_score,
            pii_detected=pii_detected,
            bias_detected=bias_detected,
            secrets_detected=secrets_detected,
            injection_detected=injection_detected,
            unavailable_detectors=unavailable_detectors,
        )
