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

import asyncio
import logging

from api.schemas import (
    ActionType,
    PolicyDecision,
    PolicyEvaluationRequest,
    RiskScore,
    UseCase,
)

logger = logging.getLogger("sentinelai")


async def evaluate_policy(
    use_case: UseCase,
    risk_score: RiskScore,
    pii_detected: bool = False,
    bias_detected: bool = False,
    secrets_detected: bool = False,
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

        loop = asyncio.get_event_loop()

        def _run():
            engine = get_policy_engine()
            return engine.evaluate(request)

        decision = await loop.run_in_executor(None, _run)

        logger.info(
            f"Policy evaluated | use_case={use_case_str} | "
            f"risk={risk_score.overall:.3f} | "
            f"action={decision.final_action} | "
            f"reason={decision.reason}"
        )
        return decision

    except Exception as e:
        logger.error(f"Policy engine failed | error={str(e)}")
        # Safe fallback — if policy engine fails, default to ALLOW
        # Pipeline continues but logs the error
        return PolicyDecision(
            approved=True,
            final_action=ActionType.ALLOW,
            reason=f"Policy engine error — defaulting to ALLOW: {str(e)}",
            policy_file="policy/engine.py",
            threshold_applied=0.0,
        )
