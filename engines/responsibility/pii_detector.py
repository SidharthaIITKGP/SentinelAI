"""
SentinelAI — PII Detector Wrapper

Thin wrapper around Aman's PresidioPIIDetector.
Exposes the async interface that core/pipeline.py expects.

Aman's actual implementation is at:
  engines/responsibility/pii_check/pii_detector.py

This wrapper provides:
  detect_pii(text, scan_target) -> PIIResult
  redact_pii(text) -> tuple[PIIResult, str]
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from api.schemas import PIIResult

logger = logging.getLogger("sentinelai")


async def detect_pii(text: str, scan_target: str = "prompt") -> PIIResult:
    """
    Detect PII in text using Presidio.
    Called twice per pipeline run:
      - Step 1 SCAN: scan_target="prompt"
      - Step 4 EVALUATE: scan_target="response"

    Args:
        text:        Text to scan for PII
        scan_target: "prompt" | "response"

    Returns:
        PIIResult with found flag, entities list, risk_score
    """
    try:
        from engines.responsibility.pii_check.pii_detector import get_pii_detector

        loop = asyncio.get_event_loop()

        def _run():
            detector = get_pii_detector()
            return detector.scan(text, scan_target=scan_target)

        result = await loop.run_in_executor(None, _run)
        logger.debug(
            f"PII scan complete | target={scan_target} | "
            f"found={result.found} | entities={result.entity_count}"
        )
        return result

    except Exception as e:
        logger.error(f"PII detector failed | error={str(e)}")
        return PIIResult(found=False, risk_score=0.0, scan_target=scan_target)


async def redact_pii(text: str) -> tuple[PIIResult, str]:
    """
    Detect and redact PII from text.
    Used by action_layer.py for REDACT action.

    Args:
        text: Text to anonymize

    Returns:
        tuple of (PIIResult, redacted_text)
    """
    try:
        from engines.responsibility.pii_check.pii_detector import get_pii_detector

        loop = asyncio.get_event_loop()

        def _run():
            detector = get_pii_detector()
            return detector.anonymize(text)

        result, redacted_text = await loop.run_in_executor(None, _run)
        logger.debug(
            f"PII redaction complete | "
            f"entities_redacted={result.entity_count}"
        )
        return result, redacted_text

    except Exception as e:
        logger.error(f"PII redaction failed | error={str(e)}")
        return PIIResult(found=False, risk_score=0.0, scan_target="response"), text
