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
    Detect bias using hybrid detection + semantic toxicity concepts.
    Called in Step 4 EVALUATE (parallel with groundedness + PII).

    Uses Aman's 4-layer hybrid detector:
      - Explicit pattern matching
      - Semantic embedding similarity
      - Toxicity classifier (HuggingFace)
      - Optional LLM bias judge
    Now also checks semantic similarity against toxic concept embeddings
    in addition to pattern matching and classifier.

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

        # Also run semantic toxicity check
        try:
            from core.injection_detector import scan_toxic_content
            if scan_toxic_content is not None:
                is_toxic, toxic_score, toxic_concept = await scan_toxic_content(text)
                if is_toxic and toxic_score > result.score:
                    # Semantic check found higher signal — use it
                    logger.info(
                        f"Semantic toxicity enhancing bias score | "
                        f"old={result.score:.3f} new={toxic_score:.3f} | "
                        f"concept={toxic_concept}"
                    )
                    result.detected = True
                    result.score = toxic_score
                    result.risk_score = toxic_score
                    result.detection_method = "semantic_embedding"
                    if not result.flagged_segments:
                        result.flagged_segments = [text[:100]]
        except Exception as e:
            logger.debug(f"Semantic toxicity check in bias detector failed: {e}")

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
