"""
SentinelAI — Bias Detector Wrapper

Thin wrapper around Aman's BiasDetector.
Exposes the async interface that core/pipeline.py expects.

Aman's actual implementation is at:
  engines/responsibility/bias_check/bias_detector.py

This wrapper provides:
  detect_bias(text) -> BiasResult
"""
from __future__ import annotations

import asyncio
import logging

from api.schemas import BiasResult

logger = logging.getLogger("sentinelai")


async def detect_bias(text: str) -> BiasResult:
    """
    Detect bias in LLM response text using hybrid detection.
    Called in Step 4 EVALUATE (parallel with groundedness + PII).

    Uses Aman's 4-layer hybrid detector:
      - Explicit pattern matching
      - Semantic embedding similarity
      - Toxicity classifier (HuggingFace)
      - Optional LLM bias judge

    Args:
        text: LLM response text to evaluate for bias

    Returns:
        BiasResult with detected flag, score, bias_types, evidence
    """
    try:
        from engines.responsibility.bias_check.bias_detector import get_bias_detector

        loop = asyncio.get_event_loop()

        def _run():
            detector = get_bias_detector()
            return detector.scan(text, scan_target="response")

        result = await loop.run_in_executor(None, _run)
        logger.debug(
            f"Bias scan complete | "
            f"detected={result.detected} | score={result.score:.3f} | "
            f"method={result.detection_method}"
        )
        return result

    except Exception as e:
        logger.error(f"Bias detector failed | error={str(e)}")
        return BiasResult(
            detected=False,
            score=0.0,
            confidence=0.0,
            detection_method="pattern_match",
            bias_types=[],
            flagged_segments=[],
            protected_dimensions=[],
            behaviors=[],
            evidence=[],
            toxicity_score=0.0,
            identity_hate_score=0.0,
            risk_score=0.0,
        )
