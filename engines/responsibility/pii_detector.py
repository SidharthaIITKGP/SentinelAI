"""Async PII detection and verified redaction wrapper for the core pipeline."""

from __future__ import annotations

import asyncio
import logging
import re

from api.schemas import DetectorStatus, PIIEntity, PIIEntityType, PIIResult

logger = logging.getLogger("sentinelai")

QUICK_PATTERNS = {
    "US_SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "CREDIT_CARD": r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b",
    "EMAIL_ADDRESS": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "PHONE_NUMBER": r"\b(?:\+\d{1,3}[\s.-])?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b",
}
GOVERNANCE_TYPES = {
    "US_SSN", "CREDIT_CARD", "IBAN_CODE", "EMAIL_ADDRESS", "PHONE_NUMBER",
    "MEDICAL_LICENSE", "IN_AADHAAR", "IN_PAN", "IN_PASSPORT",
}
RESPONSE_GOVERNANCE_TYPES = GOVERNANCE_TYPES | {"PERSON"}
HIGH_RISK_TYPES = {
    "US_SSN", "CREDIT_CARD", "IBAN_CODE", "MEDICAL_LICENSE",
    "IN_AADHAAR", "IN_PAN", "IN_PASSPORT",
}


def _regex_entities(text: str, relevant_types: set[str]) -> list[PIIEntity]:
    """Return safe regex metadata with reliable offsets, never matched values."""
    entities: list[PIIEntity] = []
    for entity_type, pattern in QUICK_PATTERNS.items():
        if entity_type not in relevant_types:
            continue
        for match in re.finditer(pattern, text):
            entities.append(
                PIIEntity(
                    entity_type=PIIEntityType(entity_type),
                    text=f"<{entity_type}>",
                    start=match.start(),
                    end=match.end(),
                    score=0.85,
                    redacted_placeholder=f"<{entity_type}>",
                    detection_method="PATTERN_VALIDATED",
                    signals=["local_regex"],
                )
            )
    return entities


async def detect_pii(text: str, scan_target: str = "prompt") -> PIIResult:
    """Detect governance-relevant PII using Presidio plus local patterns."""
    try:
        from engines.responsibility.pii_check.pii_detector import (
            ENTITY_RISK_SCORES,
            get_pii_detector,
        )

        loop = asyncio.get_event_loop()

        def _run():
            return get_pii_detector().scan(text, scan_target=scan_target)

        raw_result = await loop.run_in_executor(None, _run)
        relevant_types = (
            RESPONSE_GOVERNANCE_TYPES if scan_target == "response" else GOVERNANCE_TYPES
        )
        filtered_entities = [
            entity for entity in raw_result.entities
            if entity.entity_type in relevant_types
        ]
        regex_entities = [
            entity
            for entity in _regex_entities(text, relevant_types)
            if not any(
                existing.entity_type == entity.entity_type
                and existing.start == entity.start
                and existing.end == entity.end
                for existing in filtered_entities
            )
        ]
        all_entities = filtered_entities + regex_entities

        if not all_entities:
            return PIIResult(found=False, scan_target=scan_target)

        risk_score = max(
            ENTITY_RISK_SCORES.get(entity.entity_type, 0.30)
            for entity in all_entities
        )
        high_risk = sorted({
            entity.entity_type for entity in all_entities
            if entity.entity_type in HIGH_RISK_TYPES
        })
        logger.info(
            "PII scan completed | target=%s | count=%d | types=%s",
            scan_target,
            len(all_entities),
            sorted({entity.entity_type for entity in all_entities}),
        )
        return PIIResult(
            found=True,
            entities=all_entities,
            risk_score=risk_score,
            high_risk_entities=high_risk,
            scan_target=scan_target,
        )
    except Exception as exc:
        logger.error("PII detector unavailable: %s", type(exc).__name__)
        return PIIResult(
            found=False,
            status=DetectorStatus.UNAVAILABLE,
            scan_target=scan_target,
        )


async def redact_pii(text: str) -> tuple[PIIResult, str]:
    """Anonymize actual sensitive spans and return only safe finding metadata."""
    try:
        from engines.responsibility.pii_check.pii_detector import get_pii_detector

        loop = asyncio.get_event_loop()

        def _run():
            return get_pii_detector().anonymize(text, scan_target="response")

        result, redacted_text = await loop.run_in_executor(None, _run)

        # Apply deterministic patterns to anything Presidio left behind. Matched
        # values are used transiently and never retained in result metadata.
        regex_entities = _regex_entities(text, RESPONSE_GOVERNANCE_TYPES)
        for entity_type, pattern in QUICK_PATTERNS.items():
            redacted_text = re.sub(pattern, f"<{entity_type}>", redacted_text)

        existing_spans = {
            (entity.entity_type, entity.start, entity.end) for entity in result.entities
        }
        combined_entities = result.entities + [
            entity for entity in regex_entities
            if (entity.entity_type, entity.start, entity.end) not in existing_spans
        ]
        if combined_entities != result.entities:
            result = PIIResult(
                found=True,
                entities=combined_entities,
                risk_score=max(entity.score for entity in combined_entities),
                high_risk_entities=sorted({
                    entity.entity_type for entity in combined_entities
                    if entity.entity_type in HIGH_RISK_TYPES
                }),
                scan_target="response",
            )

        logger.info("PII redaction completed | count=%d", result.entity_count)
        return result, redacted_text
    except Exception as exc:
        logger.error("PII redaction unavailable: %s", type(exc).__name__)
        return (
            PIIResult(
                found=False,
                status=DetectorStatus.UNAVAILABLE,
                scan_target="response",
            ),
            text,
        )
