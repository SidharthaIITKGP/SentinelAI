"""
SentinelAI — Risk Scorer

Combines outputs from all 3 evaluation engines into one unified RiskScore.
Applies use-case-specific weights so different contexts produce different risk levels.

Weight logic:
  customer_chatbot → weights responsibility (PII) highest — public-facing risk
  hr_copilot       → weights bias + groundedness equally — HR decisions matter
  finance_tool     → weights groundedness highest — financial claims must be sourced

Called in Step 5 of pipeline.py after asyncio.gather completes.
Real implementation replaces the mock return on Day 2.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from api.schemas import (
    BiasResult,
    GroundednessResult,
    InjectionResult,
    PIIResult,
    RiskBreakdown,
    RiskLevel,
    RiskScore,
    UseCase,
)

logger = logging.getLogger("sentinelai")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Use-case specific weights for combining engine signals into overall risk score.
# Each use case emphasizes different risk dimensions.
# Weights must sum to 1.0 per use case.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RISK_WEIGHTS: dict[str, dict[str, float]] = {
    "customer_chatbot": {
        "injection":      0.30,   # injection = immediate trust breach for public users
        "pii_response":   0.30,   # PII leaking to customer = severe liability
        "groundedness":   0.20,   # hallucination = bad but recoverable
        "bias":           0.15,   # bias = reputational risk
        "pii_prompt":     0.05,   # PII in prompt = lower risk (employee sending it)
    },
    "hr_copilot": {
        "injection":      0.20,
        "pii_response":   0.25,   # employee PII leaking = serious
        "groundedness":   0.25,   # wrong policy info = employees act on it
        "bias":           0.25,   # bias in HR = legal liability
        "pii_prompt":     0.05,
    },
    "finance_tool": {
        "injection":      0.20,
        "pii_response":   0.20,
        "groundedness":   0.40,   # financial claims MUST be sourced — highest weight
        "bias":           0.15,
        "pii_prompt":     0.05,
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main compute function
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute(
    injection: InjectionResult,
    pii_prompt: PIIResult,
    groundedness: GroundednessResult,
    pii_response: PIIResult,
    bias: BiasResult,
    use_case: UseCase,
) -> RiskScore:
    """
    Computes a unified RiskScore from all engine outputs.

    Args:
        injection:    Result from injection_detector — was prompt injection detected?
        pii_prompt:   Result from pii_detector on the PROMPT — PII in what was sent
        groundedness: Result from groundedness engine — is response factually grounded?
        pii_response: Result from pii_detector on the RESPONSE — PII in what LLM said
        bias:         Result from bias_detector — is response biased?
        use_case:     Which use case — determines which weight profile to apply

    Returns:
        RiskScore with overall score (0-1), level (LOW/MEDIUM/HIGH),
        breakdown per signal, and use case applied.

    Note:
        groundedness.score is "how grounded" (high = good, low = bad).
        We INVERT it: groundedness_risk = 1 - groundedness.score
        so that high groundedness_risk = high hallucination risk.
        This keeps all signals pointing the same direction (higher = more risky).
    """
    logger.debug(f"Computing risk score for use_case={use_case}")

    # Get weights for this use case
    # Fall back to customer_chatbot weights if use_case not found
    weights = RISK_WEIGHTS.get(use_case, RISK_WEIGHTS["customer_chatbot"])

    # Extract individual signal scores
    injection_score = injection.confidence if injection.detected else 0.0
    pii_prompt_score = pii_prompt.risk_score
    pii_response_score = pii_response.risk_score
    groundedness_risk = 1.0 - groundedness.score   # INVERTED — low groundedness = high risk
    bias_score = bias.score

    # Weighted sum
    overall = (
        weights["injection"]    * injection_score
        + weights["pii_prompt"]   * pii_prompt_score
        + weights["pii_response"] * pii_response_score
        + weights["groundedness"] * groundedness_risk
        + weights["bias"]         * bias_score
    )

    # Clamp to [0, 1] just in case of floating point edge cases
    overall = max(0.0, min(1.0, overall))

    # Determine dominant signal — which one contributed most to the score
    signal_contributions = {
        "injection":     weights["injection"]    * injection_score,
        "pii_prompt":    weights["pii_prompt"]   * pii_prompt_score,
        "pii_response":  weights["pii_response"] * pii_response_score,
        "groundedness":  weights["groundedness"] * groundedness_risk,
        "bias":          weights["bias"]         * bias_score,
    }
    dominant_signal = max(signal_contributions, key=signal_contributions.get)

    # Build breakdown
    breakdown = RiskBreakdown(
        injection_score=injection_score,
        pii_prompt_score=pii_prompt_score,
        pii_response_score=pii_response_score,
        groundedness_risk=groundedness_risk,
        bias_score=bias_score,
        dominant_signal=dominant_signal,
    )

    # Derive level from overall score
    # Thresholds: HIGH > 0.65, MEDIUM > 0.35, LOW <= 0.35
    if overall > 0.65:
        level = RiskLevel.HIGH
    elif overall > 0.35:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW

    risk_score = RiskScore(
        overall=overall,
        level=level,
        breakdown=breakdown,
        use_case=use_case,
        computed_at=datetime.now(timezone.utc),
    )

    logger.debug(
        f"Risk score computed | overall={overall:.3f} | "
        f"level={level} | dominant={dominant_signal}"
    )

    return risk_score
