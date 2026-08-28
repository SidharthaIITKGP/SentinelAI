"""Safe, local detection and redaction of common credentials and secrets."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Final

from api.schemas import SecretFinding, SecretResult, SecretType
from engines.responsibility.pii_check.phase3_config import EntropyConfig

logger = logging.getLogger(__name__)


class SecretDetectorError(RuntimeError):
    """Raised when a secret scan cannot complete safely."""


@dataclass(frozen=True)
class _SecretPattern:
    secret_type: SecretType
    pattern: re.Pattern[str]
    score: float
    value_group: str | None = None


HIGH_RISK_SECRET_TYPES: Final = frozenset({
    SecretType.AWS_ACCESS_KEY_ID.value, SecretType.GITHUB_TOKEN.value,
    SecretType.GITLAB_TOKEN.value, SecretType.OPENAI_API_KEY.value,
    SecretType.SLACK_TOKEN.value, SecretType.JSON_WEB_TOKEN.value,
    SecretType.PRIVATE_KEY.value,
})

# Specific formats precede generic assignments so one credential produces one finding.
SECRET_PATTERNS: Final = (
    _SecretPattern(SecretType.PRIVATE_KEY, re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----[\s\S]+?-----END(?: [A-Z0-9]+)? PRIVATE KEY-----"), 1.0),
    _SecretPattern(SecretType.AWS_ACCESS_KEY_ID, re.compile(r"\b(?:AKIA|ASIA|A3T[A-Z0-9])[A-Z0-9]{16}\b"), 1.0),
    _SecretPattern(SecretType.GITHUB_TOKEN, re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b"), 1.0),
    _SecretPattern(SecretType.GITLAB_TOKEN, re.compile(r"\bglpat-[A-Za-z0-9_-]{20,255}\b"), 1.0),
    _SecretPattern(SecretType.OPENAI_API_KEY, re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,255}\b"), 1.0),
    _SecretPattern(SecretType.SLACK_TOKEN, re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,255}\b"), 0.98),
    _SecretPattern(SecretType.JSON_WEB_TOKEN, re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), 0.95),
    _SecretPattern(SecretType.GENERIC_CREDENTIAL, re.compile(r"(?i)\b(?:api[ _-]?key|secret|password|token|access[_-]?token|client[_-]?secret)\b\s*(?:[:=]|\bis\b)\s*(?:['\"])?(?P<value>[^\s'\"]{8,})(?:['\"])?"), 0.80, "value"),
)


class SecretDetector:
    """Detect and redact known credential formats without persisting values."""

    def __init__(self, entropy_config: EntropyConfig | None = None) -> None:
        self._entropy_config = entropy_config or EntropyConfig()

    def scan(self, text: str, *, scan_target: str = "prompt") -> SecretResult:
        self._validate_text(text)
        self._validate_target(scan_target)
        if not text:
            return SecretResult(found=False, scan_target=scan_target)
        try:
            findings = self._findings(text)
        except Exception as exc:
            logger.error("Secret scan failed")
            raise SecretDetectorError("Credential scan could not be completed") from exc
        high_risk = sorted({item.secret_type for item in findings if item.secret_type in HIGH_RISK_SECRET_TYPES})
        logger.info("Secret scan completed: %d credentials detected", len(findings))
        return SecretResult(found=bool(findings), findings=findings, risk_score=max((item.score for item in findings), default=0.0), high_risk_secret_types=high_risk, scan_target=scan_target)

    def anonymize(self, text: str, *, scan_target: str = "prompt") -> tuple[SecretResult, str]:
        result = self.scan(text, scan_target=scan_target)
        redacted = text
        for item in reversed(result.findings):
            redacted = redacted[:item.start] + item.redacted_placeholder + redacted[item.end:]
        logger.info("Secret anonymization completed: %d credentials redacted", result.secret_count)
        return result, redacted

    @staticmethod
    def _validate_text(text: str) -> None:
        if not isinstance(text, str):
            raise ValueError("text must be a string")

    @staticmethod
    def _validate_target(scan_target: str) -> None:
        if scan_target not in {"prompt", "response"}:
            raise ValueError("scan_target must be 'prompt' or 'response'")

    @staticmethod
    def _overlaps(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
        return any(start < existing_end and end > existing_start for existing_start, existing_end in occupied)

    def _findings(self, text: str) -> list[SecretFinding]:
        occupied: list[tuple[int, int]] = []
        findings: list[SecretFinding] = []
        for definition in SECRET_PATTERNS:
            for match in definition.pattern.finditer(text):
                start, end = match.span(definition.value_group) if definition.value_group else match.span()
                if self._overlaps(start, end, occupied):
                    continue
                value = match.group(definition.value_group) if definition.value_group else match.group(0)
                type_name, score, method, signals = self._classify_pattern_candidate(
                    definition, value, text, start, end
                )
                findings.append(SecretFinding(
                    secret_type=type_name, start=start, end=end, score=score,
                    redacted_placeholder=f"<{type_name}>", detection_method=method, signals=signals,
                ))
                occupied.append((start, end))
        return sorted(findings, key=lambda item: item.start)

    def _classify_pattern_candidate(
        self, definition: _SecretPattern, value: str, text: str, start: int, end: int
    ) -> tuple[str, float, str, list[str]]:
        if definition.secret_type is not SecretType.GENERIC_CREDENTIAL:
            return (
                definition.secret_type.value, definition.score, "KNOWN_PATTERN_SECRET",
                [f"known_format:{definition.secret_type.value.lower()}"],
            )
        entropy = self._shannon_entropy(value)
        context = self._has_secret_context(text, start, end)
        if self._is_entropy_suspected(value, entropy, context):
            return (
                SecretType.POSSIBLE_SECRET.value, 0.85, "ENTROPY_PLUS_CONTEXT",
                ["high_entropy", "character_diversity", "secret_context"],
            )
        return (
            SecretType.GENERIC_CREDENTIAL.value, definition.score, "CONTEXTUAL_PATTERN",
            ["secret_context"],
        )

    def _is_entropy_suspected(self, value: str, entropy: float, context: bool) -> bool:
        if value in self._entropy_config.allowlist or not context:
            return False
        if len(value) < self._entropy_config.minimum_length:
            return False
        if self._is_harmless_format(value):
            return False
        classes = sum((
            any(char.islower() for char in value), any(char.isupper() for char in value),
            any(char.isdigit() for char in value), any(not char.isalnum() for char in value),
        ))
        return classes >= 3 and entropy >= self._entropy_config.minimum_entropy

    @staticmethod
    def _shannon_entropy(value: str) -> float:
        length = len(value)
        return -sum((value.count(char) / length) * math.log2(value.count(char) / length) for char in set(value))

    def _has_secret_context(self, text: str, start: int, end: int) -> bool:
        window = text[max(0, start - 40): min(len(text), end + 40)].casefold()
        return any(term.casefold() in window for term in self._entropy_config.context_terms)

    @staticmethod
    def _is_harmless_format(value: str) -> bool:
        is_hex_hash = len(value) in {32, 40, 64, 128} and all(char in "0123456789abcdefABCDEF" for char in value)
        is_uuid = bool(re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value))
        return is_hex_hash or is_uuid
