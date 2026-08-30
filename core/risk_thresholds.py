"""Authoritative SentinelAI risk-level boundaries.

The scorer and schema validation both use this module so serialized risk levels
cannot disagree with the business rule. Boundaries are inclusive at 0.20 and
0.55: LOW <= 0.20, MEDIUM <= 0.55, HIGH > 0.55.
"""

from __future__ import annotations

from typing import Final


LOW_RISK_MAX: Final[float] = 0.20
MEDIUM_RISK_MAX: Final[float] = 0.55


def risk_level_value(score: float) -> str:
    """Return the canonical risk-level string for a normalized score."""
    if score <= LOW_RISK_MAX:
        return "LOW"
    if score <= MEDIUM_RISK_MAX:
        return "MEDIUM"
    return "HIGH"
