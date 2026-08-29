"""Microsoft Presidio-backed PII detection and redaction.

This module is intentionally independent from the LLM pipeline during Phase 1.
It never logs or returns raw detected values; findings contain offsets and a
category placeholder only.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Final, Optional

import regex as presidio_regex
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
import tldextract

from api.schemas import PIIEntity, PIIEntityType, PIIResult
from engines.responsibility.pii_check.phase3_config import Phase3Config, load_phase3_config

logger = logging.getLogger(__name__)

LANGUAGE: Final = "en"
NLP_MODEL: Final = "en_core_web_sm"
SUPPORTED_ENTITY_TYPES: Final = tuple(entity.value for entity in PIIEntityType)
HIGH_RISK_ENTITY_TYPES: Final = frozenset(
    {
        "CREDIT_CARD", "US_SSN", "IBAN_CODE", "MEDICAL_LICENSE",
        "IN_AADHAAR", "IN_PAN", "IN_PASSPORT",
    }
)
ENTITY_RISK_SCORES: Final = {
    "IN_AADHAAR": 0.95,
    "IN_PAN": 0.90,
    "IN_PASSPORT": 0.90,
    "CREDIT_CARD": 0.95,
    "US_SSN": 0.95,
    "IBAN_CODE": 0.90,
    "MEDICAL_LICENSE": 0.85,
    "EMAIL_ADDRESS": 0.70,
    "PHONE_NUMBER": 0.70,
    "IP_ADDRESS": 0.60,
    "PERSON": 0.50,
    "LOCATION": 0.45,
    "DATE_TIME": 0.45,
    "ORGANIZATION": 0.40,
    "URL": 0.35,
    "NRP": 0.35,
}

# Presidio's built-in EmailRecognizer delegates validation to tldextract. Use
# its packaged Public Suffix List instead of allowing a scan to make a network
# request (which would be inappropriate for an inline privacy-control path).
tldextract.extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


# Verhoeff multiplication and permutation tables. Aadhaar checksum validation
# is performed locally; this detector never contacts UIDAI or another service.
_VERHOEFF_D: Final = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P: Final = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def _is_valid_verhoeff(value: str) -> bool:
    """Validate a full digit sequence with the Verhoeff checksum algorithm."""
    checksum = 0
    for index, digit in enumerate(reversed(value)):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[index % 8][int(digit)]]
    return checksum == 0


class IndianAadhaarRecognizer(PatternRecognizer):
    """Recognize Aadhaar candidates only when their local Verhoeff checksum is valid."""

    def __init__(self) -> None:
        super().__init__(
            supported_entity="IN_AADHAAR",
            name="IndianAadhaarRecognizer",
            patterns=[Pattern("Indian Aadhaar", r"(?<!\d)[2-9]\d{3}(?:[ -]?\d{4}){2}(?!\d)", 0.75)],
            context=["aadhaar", "aadhar", "uid", "uidai", "identity number"],
            global_regex_flags=presidio_regex.DOTALL | presidio_regex.MULTILINE,
        )

    def validate_result(self, pattern_text: str) -> bool:
        digits = re.sub(r"[ -]", "", pattern_text)
        return len(digits) == 12 and digits[0] in "23456789" and _is_valid_verhoeff(digits)


class IndianPanRecognizer(PatternRecognizer):
    """Recognize syntactically valid Indian PAN values with helpful tax context."""

    def __init__(self) -> None:
        super().__init__(
            supported_entity="IN_PAN",
            name="IndianPanRecognizer",
            patterns=[Pattern("Indian PAN", r"(?<![A-Z0-9])[A-Z]{5}[0-9]{4}[A-Z](?![A-Z0-9])", 0.75)],
            context=["pan", "permanent account number", "income tax", "tax identifier"],
            global_regex_flags=(
                presidio_regex.DOTALL | presidio_regex.MULTILINE | presidio_regex.IGNORECASE
            ),
        )

    def validate_result(self, pattern_text: str) -> Optional[bool]:
        normalized = pattern_text.upper()
        is_valid = (
            len(normalized) == 10
            and normalized[:5].isalpha()
            and normalized[:5].isupper()
            and normalized[5:9].isdigit()
            and normalized[9].isalpha()
            and normalized[9].isupper()
        )
        # Keep the base score for a structurally valid value. Context below,
        # rather than the shape alone, determines whether it is high confidence.
        return None if is_valid else False

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts: Optional[object] = None,
        regex_flags: Optional[int] = None,
    ) -> list[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        for result in results:
            window = text[max(0, result.start - 60): min(len(text), result.end + 60)].lower()
            if any(term in window for term in ("pan", "permanent account number", "income tax", "tax identifier")):
                result.score = 1.0
            else:
                result.score = min(result.score, 0.75)
        return results


class IndianPassportRecognizer(PatternRecognizer):
    """Conservatively recognize Indian passport numbers only near passport context."""

    _CONTEXT = re.compile(r"\b(?:passport|passport\s+number|travel\s+document)\b", re.IGNORECASE)

    def __init__(self) -> None:
        super().__init__(
            supported_entity="IN_PASSPORT",
            name="IndianPassportRecognizer",
            patterns=[Pattern("Indian Passport", r"(?<![A-Z0-9])[A-Z][0-9]{7}(?![A-Z0-9])", 0.65)],
            context=["passport", "passport number", "travel document"],
            global_regex_flags=presidio_regex.DOTALL | presidio_regex.MULTILINE,
        )

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts: Optional[object] = None,
        regex_flags: Optional[int] = None,
    ) -> list[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        return [
            result for result in results
            if self._CONTEXT.search(text[max(0, result.start - 60): min(len(text), result.end + 60)])
        ]


class TaxonomyRecognizer(PatternRecognizer):
    """Presidio recognizer for configurable domain dictionaries and aliases."""

    def __init__(self, entity_type: str, entries: dict[str, tuple[str, ...]], name: str) -> None:
        self._methods = {
            alias.casefold(): "DICTIONARY" if alias.casefold() == concept.casefold() else "ALIAS"
            for concept, aliases in entries.items()
            for alias in aliases
        }
        patterns = [
            Pattern(name="taxonomy", regex=rf"(?<!\w){re.escape(alias)}(?!\w)", score=0.85)
            for aliases in entries.values() for alias in aliases
        ]
        super().__init__(
            supported_entity=entity_type,
            name=name,
            patterns=patterns,
            global_regex_flags=presidio_regex.DOTALL | presidio_regex.MULTILINE | presidio_regex.IGNORECASE,
        )

    def analyze(
        self, text: str, entities: list[str], nlp_artifacts: Optional[object] = None,
        regex_flags: Optional[int] = None,
    ) -> list[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        for result in results:
            matched = text[result.start:result.end].casefold()
            result.recognition_metadata["detection_method"] = self._methods.get(matched, "DICTIONARY")
            result.recognition_metadata["signals"] = ["taxonomy_match"]
        return results


class PresidioServiceError(RuntimeError):
    """Raised when Presidio cannot initialize or analyze text safely."""


class PresidioPIIDetector:
    """Clean service boundary around Presidio's analyzer and anonymizer engines."""

    def __init__(self, phase3_config: Phase3Config | None = None) -> None:
        try:
            self._phase3_config = phase3_config or load_phase3_config()
            provider = NlpEngineProvider(
                nlp_configuration={
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": LANGUAGE, "model_name": NLP_MODEL}],
                }
            )
            self._analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())
            self._analyzer.registry.add_recognizer(IndianAadhaarRecognizer())
            self._analyzer.registry.add_recognizer(IndianPanRecognizer())
            self._analyzer.registry.add_recognizer(IndianPassportRecognizer())
            for entity_type, entries, name in (
                ("PERSON", self._phase3_config.people, "DomainPersonRecognizer"),
                ("DOMAIN_ORGANIZATION", self._phase3_config.organizations, "DomainOrganizationRecognizer"),
                ("DOMAIN_PROJECT", self._phase3_config.projects, "DomainProjectRecognizer"),
                ("DOMAIN_TERM", self._phase3_config.domain_terms, "DomainTermRecognizer"),
            ):
                if entries:
                    self._analyzer.registry.add_recognizer(TaxonomyRecognizer(entity_type, entries, name))
            self._anonymizer = AnonymizerEngine()
            available = set(self._analyzer.get_supported_entities())
            self._entities = [entity for entity in SUPPORTED_ENTITY_TYPES if entity in available]
            if not self._entities:
                raise PresidioServiceError("No configured PII recognizers are available")
        except PresidioServiceError:
            raise
        except Exception as exc:
            # Keep model/environment details out of API responses and raw text out of logs.
            logger.error("Presidio initialization failed")
            raise PresidioServiceError(
                "Presidio could not initialize. Install the configured spaCy model "
                f"({NLP_MODEL})."
            ) from exc

    def scan(self, text: str, *, scan_target: str = "prompt") -> PIIResult:
        """Analyze text and return safe, structured PII metadata.

        ``text`` is never included in a returned finding or log record. Empty
        strings are valid and return a no-findings result.
        """
        self._validate_text(text)
        self._validate_target(scan_target)
        if not text:
            return PIIResult(found=False, scan_target=scan_target)

        try:
            results = self._analyzer.analyze(
                text=text, language=LANGUAGE, entities=self._entities
            )
        except Exception as exc:
            logger.error("Presidio scan failed")
            raise PresidioServiceError("Presidio could not scan the supplied text") from exc

        entities = [self._safe_entity(result) for result in results]
        high_risk = sorted({entity.entity_type for entity in entities if entity.entity_type in HIGH_RISK_ENTITY_TYPES})
        risk_score = max((ENTITY_RISK_SCORES.get(entity.entity_type, 0.30) for entity in entities), default=0.0)
        logger.info("Presidio scan completed: %d entities detected", len(entities))
        return PIIResult(
            found=bool(entities),
            entities=entities,
            risk_score=risk_score,
            high_risk_entities=high_risk,
            scan_target=scan_target,
        )

    def anonymize(self, text: str, *, scan_target: str = "prompt") -> tuple[PIIResult, str]:
        """Return scan metadata plus text where every finding is category-redacted."""
        result = self.scan(text, scan_target=scan_target)
        if not result.found:
            return result, text
        operators = {
            entity.entity_type: OperatorConfig(
                "replace", {"new_value": entity.redacted_placeholder}
            )
            for entity in result.entities
        }
        redaction_entities = self._select_redaction_entities(result.entities)
        try:
            anonymized = self._anonymizer.anonymize(
                text=text,
                analyzer_results=[
                    RecognizerResult(
                        entity_type=entity.entity_type,
                        start=entity.start,
                        end=entity.end,
                        score=entity.score,
                    )
                    for entity in redaction_entities
                ],
                operators=operators,
            )
        except Exception as exc:
            logger.error("Presidio anonymization failed")
            raise PresidioServiceError("Presidio could not anonymize the supplied text") from exc
        logger.info("Presidio anonymization completed: %d entities redacted", result.entity_count)
        return result, anonymized.text

    @staticmethod
    def _validate_text(text: str) -> None:
        if not isinstance(text, str):
            raise ValueError("text must be a string")

    @staticmethod
    def _safe_entity(result: RecognizerResult) -> PIIEntity:
        metadata = result.recognition_metadata or {}
        method = metadata.get("detection_method")
        if not method:
            name = metadata.get(RecognizerResult.RECOGNIZER_NAME_KEY, "")
            method = "MODEL_NER" if "Spacy" in name else "PATTERN_VALIDATED"
        signals = metadata.get("signals", [])
        return PIIEntity(
            entity_type=result.entity_type,
            text=f"<{result.entity_type}>",
            start=result.start,
            end=result.end,
            score=result.score,
            redacted_placeholder=f"<{result.entity_type}>",
            detection_method=method,
            signals=signals,
        )

    @staticmethod
    def _validate_target(scan_target: str) -> None:
        if scan_target not in {"prompt", "response"}:
            raise ValueError("scan_target must be 'prompt' or 'response'")

    @staticmethod
    def _select_redaction_entities(entities: list[PIIEntity]) -> list[PIIEntity]:
        """Resolve overlap in favour of high-risk validated identifiers.

        Presidio's anonymizer otherwise favours the longest overlapping span,
        which can replace a validated identifier with a broad NER result.
        """
        selected: list[PIIEntity] = []
        ordered = sorted(
            entities,
            key=lambda entity: (
                entity.entity_type not in HIGH_RISK_ENTITY_TYPES,
                -entity.score,
                -(entity.end - entity.start),
                entity.start,
            ),
        )
        for entity in ordered:
            if any(entity.start < chosen.end and entity.end > chosen.start for chosen in selected):
                continue
            selected.append(entity)
        return sorted(selected, key=lambda entity: entity.start)


@lru_cache(maxsize=1)
def get_pii_detector() -> PresidioPIIDetector:
    """Return the process-wide Presidio service, initialized lazily once."""
    return PresidioPIIDetector()
