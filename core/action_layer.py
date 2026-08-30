"""
SentinelAI — Action Layer

Executes the governed action based on risk score + policy decision.
This is where SentinelAI actually DOES something to the LLM response.

Five possible actions:
  ALLOW    → response passes through unchanged
  REPAIR   → hallucination detected — re-prompt LLM with source context
  REDACT   → PII found in response — mask entities with placeholders
  BLOCK    → risk too high — return safe fallback, NEVER return LLM response
  ESCALATE → high-risk regulated context — flag for human review

Called in Step 5 of pipeline.py after risk scoring and policy evaluation.
Real implementation of REPAIR and REDACT wired in Day 3.
"""

from __future__ import annotations

import logging
from typing import Optional

from api.schemas import (
    ActionResult,
    ActionType,
    DetectorStatus,
    PIIResult,
    PolicyDecision,
    RiskScore,
    UseCase,
)
from engines.responsibility.pii_detector import redact_pii

logger = logging.getLogger("sentinelai")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Safe fallback responses returned when action is BLOCK.
# Never return the original LLM response on BLOCK.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BLOCK_MESSAGES: dict[str, str] = {
    "customer_chatbot": (
        "I'm sorry, I'm unable to assist with that request. "
        "Please contact our support team at support@acmecorp.com "
        "or call 1-800-ACME-HELP for further assistance."
    ),
    "hr_copilot": (
        "This request cannot be processed automatically. "
        "Please contact the HR department directly at hr@acmecorp.com "
        "or raise a ticket through the HR portal."
    ),
    "finance_tool": (
        "This response has been flagged for compliance review and cannot be "
        "returned automatically. Please contact the Finance team or your "
        "compliance officer for guidance on this matter."
    ),
}

DEFAULT_BLOCK_MESSAGE = (
    "I'm unable to process this request. "
    "Please contact support if you believe this is an error."
)

ESCALATION_MESSAGES: dict[str, str] = {
    "customer_chatbot": (
        "This response is being held for human review before delivery. "
        "Please try again later or contact support for assistance."
    ),
    "hr_copilot": (
        "This response is being held for mandatory HR review and has not been "
        "released. Please contact the HR team if the matter is urgent."
    ),
    "finance_tool": (
        "This response is being held for mandatory finance and compliance "
        "review and has not been released."
    ),
}

DEFAULT_ESCALATION_MESSAGE = (
    "This response is being held for mandatory human review and has not been released."
)


def _use_case_key(use_case: UseCase) -> str:
    return str(getattr(use_case, "value", use_case))


def _holding_message(use_case: UseCase) -> str:
    return ESCALATION_MESSAGES.get(_use_case_key(use_case), DEFAULT_ESCALATION_MESSAGE)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main execute function
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def execute(
    policy_decision: PolicyDecision,
    risk_score: RiskScore,
    llm_response: str,
    pii_in_response: PIIResult,
    use_case: UseCase,
) -> ActionResult:
    """
    Executes the governed action determined by the policy engine.

    Args:
        policy_decision: OPA policy engine's decision — which action to take
        risk_score:      Combined risk score from all engines
        llm_response:    Raw LLM response before any action
        pii_in_response: PII detected in the LLM response (used for REDACT)
        use_case:        Which use case — affects fallback messages

    Returns:
        ActionResult with the final response, action taken, evidence, and explanation.

    Critical invariants enforced by ActionResult validator in schemas.py:
        BLOCK  → final_response must NOT equal original_response (safe fallback used)
        ALLOW  → final_response must equal original_response (untouched)
        ESCALATE → final response is a holding message and review is required
    """
    action = policy_decision.final_action
    logger.info(f"Executing action={action} | risk={risk_score.overall:.3f}")

    # ── ALLOW ──────────────────────────────────────────────────────────────
    if action == ActionType.ALLOW:
        degraded = (
            policy_decision.policy_file in {
                "policy/availability_guard",
                "policy/fail_safe_fallback",
            }
        )
        return ActionResult(
            action=ActionType.ALLOW,
            final_response=llm_response,
            original_response=llm_response,
            explanation=(
                policy_decision.reason
                if degraded
                else (
                    f"Response passed all available checks. Risk score "
                    f"{risk_score.overall:.3f} is below threshold."
                )
            ),
            evidence={
                "risk_score": risk_score.overall,
                "risk_level": risk_score.level,
                "dominant_signal": risk_score.breakdown.dominant_signal,
                "policy_file": policy_decision.policy_file,
                "policy_reason": policy_decision.reason,
                "degraded_mode": degraded,
            },
        )

    # ── REPAIR ─────────────────────────────────────────────────────────────
    elif action == ActionType.REPAIR:
        # TODO Day 3: implement real repair
        # Real implementation:
        #   1. Get the flagged claims from groundedness result
        #   2. Get the supporting source documents from groundedness result
        #   3. Re-prompt LLM: "Answer ONLY based on: {sources}. Question: {prompt}"
        #   4. Return repaired response
        # For now: return original response with repair flag
        logger.info(
            "REPAIR action — re-prompting LLM with source context (STUBBED Day 3)"
        )
        repaired_response = (
            f"{llm_response}\n\n"
            f"[Note: This response has been reviewed for accuracy. "
            f"Please verify key claims with official documentation.]"
        )
        return ActionResult(
            action=ActionType.REPAIR,
            final_response=repaired_response,
            original_response=llm_response,
            explanation=(
                f"Hallucination risk detected (groundedness risk: "
                f"{risk_score.breakdown.groundedness_risk:.3f}). "
                f"Response flagged for accuracy."
            ),
            evidence={
                "risk_score": risk_score.overall,
                "groundedness_risk": risk_score.breakdown.groundedness_risk,
                "policy_file": policy_decision.policy_file,
                "repair_method": "stub — real LLM re-prompt wired Day 3",
            },
            repair_attempted=True,
        )

    # ── REDACT ─────────────────────────────────────────────────────────────
    elif action == ActionType.REDACT:
        logger.info(
            f"REDACT action — masking {pii_in_response.entity_count} "
            "PII entities"
        )

        try:
            redaction_result, redacted_response = await redact_pii(llm_response)
            valid_original_spans = [
                llm_response[entity.start:entity.end]
                for entity in pii_in_response.entities
                if 0 <= entity.start < entity.end <= len(llm_response)
            ]
            leaked_detected_span = any(
                raw_span and raw_span in redacted_response
                for raw_span in valid_original_spans
            )
            redaction_succeeded = (
                redaction_result.status == DetectorStatus.AVAILABLE
                and redaction_result.found
                and redacted_response != llm_response
                and not leaked_detected_span
            )
        except Exception:
            logger.exception("PII anonymization failed without logging response content")
            redaction_succeeded = False
            redaction_result = None
            redacted_response = llm_response

        if not redaction_succeeded:
            logger.error(
                "REDACT failed or left a detected span; holding response for review"
            )
            return ActionResult(
                action=ActionType.ESCALATE,
                final_response=_holding_message(use_case),
                original_response=llm_response,
                explanation=(
                    "PII was detected, but anonymization could not be verified. "
                    "The response is held for mandatory human review."
                ),
                evidence={
                    "risk_score": risk_score.overall,
                    "pii_entities_found": pii_in_response.entity_count,
                    "entity_types": [e.entity_type for e in pii_in_response.entities],
                    "policy_file": policy_decision.policy_file,
                    "redaction_status": "UNAVAILABLE_OR_INCOMPLETE",
                    "fallback_rule": "redaction_failure_hold",
                },
                escalation_required=True,
            )

        return ActionResult(
            action=ActionType.REDACT,
            final_response=redacted_response,
            original_response=llm_response,
            explanation=(
                f"{redaction_result.entity_count} PII entities detected "
                f"and redacted from response."
            ),
            evidence={
                "risk_score": risk_score.overall,
                "pii_entities_found": redaction_result.entity_count,
                "entity_types": [e.entity_type for e in redaction_result.entities],
                "high_risk_entities": redaction_result.high_risk_entities,
                "policy_file": policy_decision.policy_file,
                "redaction_status": "VERIFIED",
            },
            redacted_entity_count=redaction_result.entity_count,
        )

    # ── BLOCK ──────────────────────────────────────────────────────────────
    elif action == ActionType.BLOCK:
        # CRITICAL: NEVER return the original LLM response on BLOCK
        # Always return a safe fallback message
        fallback = BLOCK_MESSAGES.get(_use_case_key(use_case), DEFAULT_BLOCK_MESSAGE)
        logger.warning(
            f"BLOCK action — risk={risk_score.overall:.3f} exceeded threshold "
            f"{policy_decision.threshold_applied:.3f} for {use_case}"
        )
        return ActionResult(
            action=ActionType.BLOCK,
            final_response=fallback,
            original_response=llm_response,
            explanation=(
                f"Response blocked. Risk score {risk_score.overall:.3f} exceeded "
                f"the {use_case} block threshold of "
                f"{policy_decision.threshold_applied:.3f}."
            ),
            evidence={
                "risk_score": risk_score.overall,
                "risk_level": risk_score.level,
                "threshold_applied": policy_decision.threshold_applied,
                "dominant_signal": risk_score.breakdown.dominant_signal,
                "policy_file": policy_decision.policy_file,
                "policy_reason": policy_decision.reason,
            },
        )

    # ── ESCALATE ───────────────────────────────────────────────────────────
    elif action == ActionType.ESCALATE:
        logger.warning(
            f"ESCALATE action — high risk response flagged for human review | "
            f"use_case={use_case} | risk={risk_score.overall:.3f}"
        )
        return ActionResult(
            action=ActionType.ESCALATE,
            final_response=_holding_message(use_case),
            original_response=llm_response,
            explanation=(
                f"Response flagged for mandatory human review. "
                f"Risk score {risk_score.overall:.3f} in regulated use case "
                f"'{use_case}' requires compliance sign-off before delivery."
            ),
            evidence={
                "risk_score": risk_score.overall,
                "risk_level": risk_score.level,
                "dominant_signal": risk_score.breakdown.dominant_signal,
                "threshold_applied": policy_decision.threshold_applied,
                "policy_file": policy_decision.policy_file,
                "escalation_reason": policy_decision.reason,
            },
            escalation_required=True,
        )

    # ── FALLBACK (should never reach here) ─────────────────────────────────
    else:
        logger.error(f"Unknown action type: {action} — defaulting to BLOCK")
        fallback = BLOCK_MESSAGES.get(_use_case_key(use_case), DEFAULT_BLOCK_MESSAGE)
        return ActionResult(
            action=ActionType.BLOCK,
            final_response=fallback,
            original_response=llm_response,
            explanation=f"Unknown action '{action}' — defaulted to BLOCK for safety.",
            evidence={"error": f"Unknown action type: {action}"},
        )
