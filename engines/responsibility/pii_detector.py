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
    Detect PII in text using Presidio + regex pre-check.

    For RESPONSE scanning — only flags genuinely sensitive PII.
    ORGANIZATION, URL, DATE_TIME, LOCATION excluded from response
    scanning to prevent false positives on normal business text.

    For PROMPT scanning — catches high-risk identifiers users send in.
    """
    import re

    # Quick regex patterns — catch what Presidio sometimes misses
    QUICK_PATTERNS = {
        "US_SSN":        r"\b\d{3}-\d{2}-\d{4}\b",
        "CREDIT_CARD":   r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b",
        "EMAIL_ADDRESS": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "PHONE_NUMBER":  r"\b(\+\d{1,3}[\s.-])?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b",
    }

    # Only these entity types matter for governance decisions
    # Everything else (ORGANIZATION, URL, DATE_TIME, LOCATION) is noise
    GOVERNANCE_TYPES = {
        "US_SSN", "CREDIT_CARD", "IBAN_CODE",
        "EMAIL_ADDRESS", "PHONE_NUMBER",
        "MEDICAL_LICENSE", "IN_AADHAAR", "IN_PAN", "IN_PASSPORT",
    }

    # For response scanning — PERSON names in responses are also risky
    # e.g. "John Smith's account shows..."
    RESPONSE_GOVERNANCE_TYPES = GOVERNANCE_TYPES | {"PERSON"}

    try:
        from engines.responsibility.pii_check.pii_detector import (
            get_pii_detector,
            ENTITY_RISK_SCORES,
        )
        from api.schemas import PIIEntity, PIIEntityType

        loop = asyncio.get_event_loop()

        def _run():
            detector = get_pii_detector()
            return detector.scan(text, scan_target=scan_target)

        raw_result = await loop.run_in_executor(None, _run)

        # Determine which types are relevant for this scan target
        relevant_types = (
            RESPONSE_GOVERNANCE_TYPES
            if scan_target == "response"
            else GOVERNANCE_TYPES
        )

        # Filter Presidio entities — keep only governance-relevant types
        filtered_entities = [
            e for e in raw_result.entities
            if e.entity_type in relevant_types
        ]

        # Quick regex check — catch what Presidio missed
        regex_entity_types = []
        for entity_type, pattern in QUICK_PATTERNS.items():
            if entity_type in relevant_types and re.search(pattern, text):
                # Only add if Presidio didn't already find it
                already_found = any(
                    e.entity_type == entity_type
                    for e in filtered_entities
                )
                if not already_found:
                    regex_entity_types.append(entity_type)
                    logger.debug(
                        f"Regex caught {entity_type} that Presidio missed | "
                        f"target={scan_target}"
                    )

        # Build regex-caught entities
        regex_entities = []
        for entity_type in regex_entity_types:
            try:
                regex_entities.append(PIIEntity(
                    entity_type=PIIEntityType(entity_type),
                    text=f"<{entity_type}>",
                    start=0,
                    end=0,
                    score=0.85,
                    redacted_placeholder=f"<{entity_type}>",
                ))
            except Exception:
                pass

        # Combine filtered Presidio + regex entities
        all_entities = filtered_entities + regex_entities

        if not all_entities:
            logger.debug(
                f"PII scan: no governance-relevant entities | "
                f"target={scan_target} | "
                f"raw_count={raw_result.entity_count}"
            )
            return PIIResult(
                found=False,
                risk_score=0.0,
                scan_target=scan_target,
                entity_count=0,
            )

        # Calculate risk score
        risk_score = max(
            ENTITY_RISK_SCORES.get(e.entity_type, 0.30)
            for e in all_entities
        )
        high_risk = [
            e.entity_type for e in all_entities
            if e.entity_type in {
                "US_SSN", "CREDIT_CARD", "IBAN_CODE",
                "MEDICAL_LICENSE", "IN_AADHAAR", "IN_PAN"
            }
        ]

        logger.info(
            f"PII scan | target={scan_target} | "
            f"raw={raw_result.entity_count} | "
            f"filtered={len(all_entities)} | "
            f"types={[e.entity_type for e in all_entities]}"
        )

        return PIIResult(
            found=True,
            entities=all_entities,
            risk_score=risk_score,
            entity_count=len(all_entities),
            high_risk_entities=high_risk,
            scan_target=scan_target,
        )

    except Exception as e:
        logger.error(f"PII detector failed | error={str(e)}")
        return PIIResult(
            found=False,
            risk_score=0.0,
            scan_target=scan_target
        )


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
