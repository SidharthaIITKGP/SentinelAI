"""
SentinelAI — Model Router (Gaurav's module)

Selects the appropriate LLM model based on risk_level + use_case.
Returns a ModelConfig object (imported from api.schemas — not redefined here).

Routing table:
  LOW    + internal     → groq/qwen/qwen3.8-27b  (fast + cheap)
  MEDIUM + customer     → gpt-4o                  (quality matters)
  HIGH   + customer     → gpt-4o                  (full capability)
  HIGH   + finance      → gpt-4o                  (regulated)
  Any    + Any          → groq/qwen/qwen3.8-27b   (default fallback — FIX #6)
"""

from __future__ import annotations

import logging

from api.schemas import ModelConfig, RiskLevel, UseCase

logger = logging.getLogger("sentinelai.model_router")

# ── Constants ──────────────────────────────────────────────────────────────────

# FIX #6: default model changed from gpt-4o-mini to groq/qwen/qwen3.8-27b
DEFAULT_MODEL = "groq/qwen/qwen3.8-27b"
PREMIUM_MODEL = "gpt-4o"

# Customer-facing use cases (require higher quality when stakes are high)
CUSTOMER_FACING = {
    UseCase.CUSTOMER_CHATBOT,
    UseCase.FINANCE_TOOL,
}

# Internal / lower-risk use cases
INTERNAL_USE_CASES = {
    UseCase.HR_COPILOT,
}


def route_model(risk_level: RiskLevel | str, use_case: UseCase | str) -> ModelConfig:
    """
    Select the LLM model configuration for this request.

    Args:
        risk_level: LOW | MEDIUM | HIGH (RiskLevel enum or string)
        use_case:   customer_chatbot | hr_copilot | finance_tool

    Returns:
        ModelConfig — which model to use, token budget, temperature, reason
    """
    # Normalise to enum values (handle both enum and string input from pipeline)
    if isinstance(risk_level, str):
        try:
            risk_level = RiskLevel(risk_level.upper())
        except ValueError:
            risk_level = RiskLevel.LOW

    if isinstance(use_case, str):
        try:
            use_case = UseCase(use_case.lower())
        except ValueError:
            use_case = UseCase.CUSTOMER_CHATBOT

    # ── Routing logic ──────────────────────────────────────────────────────────

    # HIGH risk + finance → regulated domain, needs best model
    if risk_level == RiskLevel.HIGH and use_case == UseCase.FINANCE_TOOL:
        model = PREMIUM_MODEL
        reason = "Finance tool — HIGH risk — regulated domain requires full capability"
        max_tokens = 800
        temperature = 0.1

    # HIGH risk + customer-facing → full capability
    elif risk_level == RiskLevel.HIGH and use_case == UseCase.CUSTOMER_CHATBOT:
        model = PREMIUM_MODEL
        reason = "Customer chatbot — HIGH risk — full capability required"
        max_tokens = 800
        temperature = 0.2

    # MEDIUM risk + customer-facing → quality matters
    elif risk_level == RiskLevel.MEDIUM and use_case in CUSTOMER_FACING:
        model = PREMIUM_MODEL
        reason = f"{use_case.value} — MEDIUM risk — quality matters for customer-facing"
        max_tokens = 600
        temperature = 0.3

    # LOW risk + any internal → fast and cheap
    elif risk_level == RiskLevel.LOW and use_case in INTERNAL_USE_CASES:
        model = DEFAULT_MODEL
        reason = "Internal use case — LOW risk — fast + cheap"
        max_tokens = 400
        temperature = 0.3

    # Any other (LOW customer-facing, HIGH internal, etc.) → default fallback
    else:
        model = DEFAULT_MODEL
        reason = f"Default fallback — risk={risk_level.value} use_case={use_case.value}"
        max_tokens = 500
        temperature = 0.3

    config = ModelConfig(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        reason=reason,
    )

    logger.info(
        f"Model routed | risk={risk_level.value} | use_case={use_case.value} "
        f"| model={model} | reason={reason}"
    )

    return config
