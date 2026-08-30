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
REDACT uses verified anonymization. REPAIR permits one local-evidence-constrained
generation and releases it only after a supported groundedness recheck.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from api.schemas import (
    ActionResult,
    ActionType,
    DetectorStatus,
    GroundednessResult,
    GroundednessVerdict,
    PIIResult,
    PolicyDecision,
    RiskScore,
    UseCase,
)
from engines.responsibility.pii_detector import redact_pii

logger = logging.getLogger("sentinelai")

RepairCallback = Callable[[str], Awaitable[tuple[str, GroundednessResult]]]


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


def _repair_prompt(
    original_prompt: str,
    original_response: str,
    groundedness: GroundednessResult,
) -> tuple[str, list[str], list[str]]:
    """Build a bounded correction prompt solely from contradictory local evidence."""
    evidence_rows: list[str] = []
    source_ids: list[str] = []
    source_titles: list[str] = []
    for evaluation in groundedness.claim_evaluations:
        if (
            evaluation.verdict != GroundednessVerdict.CONTRADICTED
            or not evaluation.source_excerpt
        ):
            continue
        source_id = evaluation.source_doc_id or "unknown"
        title = evaluation.source_title or "Untitled evidence"
        if source_id not in source_ids:
            source_ids.append(source_id)
            source_titles.append(title)
            evidence_rows.append(
                f"SOURCE {source_id} — {title}:\n{evaluation.source_excerpt}"
            )

    evidence_text = "\n\n".join(evidence_rows)
    prompt = (
        "Correct the answer using only the supplied local evidence. Do not add facts "
        "from memory. If the evidence is insufficient, explicitly say so. Return only "
        "the corrected answer, with no reasoning or preamble.\n\n"
        f"ORIGINAL QUESTION:\n{original_prompt}\n\n"
        f"ORIGINAL RESPONSE:\n{original_response}\n\n"
        f"LOCAL EVIDENCE:\n{evidence_text}"
    )
    return prompt, source_ids, source_titles


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main execute function
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def execute(
    policy_decision: PolicyDecision,
    risk_score: RiskScore,
    llm_response: str,
    pii_in_response: PIIResult,
    use_case: UseCase,
    original_prompt: str = "",
    groundedness_result: Optional[GroundednessResult] = None,
    repair_callback: Optional[RepairCallback] = None,
) -> ActionResult:
    """
    Executes the governed action determined by the policy engine.

    Args:
        policy_decision: deterministic policy-as-code decision — which action to take
        risk_score:      Combined risk score from all engines
        llm_response:    Raw LLM response before any action
        pii_in_response: PII detected in the LLM response (used for REDACT)
        use_case:        Which use case — affects fallback messages
        original_prompt: User question included in an evidence-constrained repair
        groundedness_result: Initial claim verdicts and local evidence references
        repair_callback: Pipeline-owned bounded generation and verification callback

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
        before_verdict = (
            groundedness_result.verdict if groundedness_result else None
        )
        base_evidence = {
            "risk_score": risk_score.overall,
            "groundedness_risk": risk_score.breakdown.groundedness_risk,
            "policy_file": policy_decision.policy_file,
            "repair_attempted": False,
            "repair_attempts": 0,
            "before_verdict": before_verdict,
            "after_verdict": None,
            "source_doc_ids": [],
            "source_titles": [],
            "flagged_claim_count": (
                len(groundedness_result.flagged_claims)
                if groundedness_result
                else 0
            ),
            "repair_success": False,
        }
        if (
            groundedness_result is None
            or groundedness_result.verdict != GroundednessVerdict.CONTRADICTED
            or repair_callback is None
            or pii_in_response.found
        ):
            return ActionResult(
                action=ActionType.ESCALATE,
                final_response=_holding_message(use_case),
                original_response=llm_response,
                explanation=(
                    "A safe evidence-constrained repair was not available. "
                    "The original response is held for human review."
                ),
                evidence=base_evidence,
                escalation_required=True,
            )

        repair_prompt, source_ids, source_titles = _repair_prompt(
            original_prompt, llm_response, groundedness_result
        )
        base_evidence.update(
            {
                "source_doc_ids": source_ids,
                "source_titles": source_titles,
            }
        )
        if not source_ids:
            return ActionResult(
                action=ActionType.ESCALATE,
                final_response=_holding_message(use_case),
                original_response=llm_response,
                explanation="Contradiction evidence was incomplete; response held for review.",
                evidence=base_evidence,
                escalation_required=True,
            )

        base_evidence["repair_attempted"] = True
        base_evidence["repair_attempts"] = 1
        try:
            repaired_response, recheck = await repair_callback(repair_prompt)
            base_evidence["after_verdict"] = recheck.verdict
        except Exception as exc:
            logger.warning("Bounded repair failed: %s", type(exc).__name__)
            repaired_response = ""
            recheck = None
            base_evidence["after_verdict"] = GroundednessVerdict.UNAVAILABLE

        if recheck is not None and recheck.verdict == GroundednessVerdict.SUPPORTED:
            base_evidence["repair_success"] = True
            return ActionResult(
                action=ActionType.REPAIR,
                final_response=repaired_response,
                original_response=llm_response,
                explanation="Contradicted claims were corrected from local evidence and re-verified.",
                evidence=base_evidence,
                repair_attempted=True,
                repair_attempts=1,
            )

        return ActionResult(
            action=ActionType.ESCALATE,
            final_response=_holding_message(use_case),
            original_response=llm_response,
            explanation=(
                "The one permitted repair attempt did not verify as supported. "
                "Both responses are held for human review."
            ),
            evidence=base_evidence,
            escalation_required=True,
            repair_attempted=True,
            repair_attempts=1,
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
