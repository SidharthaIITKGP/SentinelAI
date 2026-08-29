"""Embedding-based contextual confidential-information detection for Phase 3.

The detector classifies sentence-sized text segments against a small, local
reference taxonomy. It returns only categories and offsets, never the segment
text, and makes no policy decision.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Final, Protocol, Sequence

from api.schemas import ConfidentialCategory, ConfidentialFinding, ConfidentialResult
from engines.responsibility.pii_check.phase3_config import Phase3Config, load_phase3_config

logger = logging.getLogger(__name__)

MODEL_NAME: Final = "all-MiniLM-L6-v2"
SIMILARITY_THRESHOLD: Final = 0.72
SENTENCE_BOUNDARY: Final = re.compile(r"(?<=[.!?])\s+|\n+")


class EmbeddingModel(Protocol):
    def encode(self, sentences: Sequence[str], *, normalize_embeddings: bool) -> Sequence[Sequence[float]]: ...


class ConfidentialDetectorError(RuntimeError):
    """Raised when the embedding model is unavailable or classification fails."""


class ContextualConfidentialDetector:
    """Classify contextual confidential information using sentence embeddings."""

    def __init__(
        self, model: EmbeddingModel | None = None, *, threshold: float | None = None,
        phase3_config: Phase3Config | None = None,
    ) -> None:
        self._config = phase3_config or load_phase3_config()
        threshold = self._config.semantic_threshold if threshold is None else threshold
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        self._model = model or self._load_model()
        self._threshold = threshold
        self._reference_vectors = self._encode(self._reference_texts())

    def scan(self, text: str, *, scan_target: str = "prompt") -> ConfidentialResult:
        self._validate_text(text)
        self._validate_target(scan_target)
        if not text:
            return ConfidentialResult(detected=False, scan_target=scan_target)
        try:
            segments = self._segments(text)
            vectors = self._encode([segment for segment, _, _ in segments]) if segments else []
            findings = self._classify(segments, vectors)
        except ConfidentialDetectorError:
            raise
        except Exception as exc:
            logger.error("Confidential-information scan failed")
            raise ConfidentialDetectorError("Contextual confidential-information scan could not be completed") from exc
        logger.info("Confidential-information scan completed: %d segments detected", len(findings))
        return ConfidentialResult(
            detected=bool(findings),
            findings=findings,
            risk_score=max((finding.score for finding in findings), default=0.0),
            scan_target=scan_target,
        )

    def anonymize(self, text: str, *, scan_target: str = "prompt") -> tuple[ConfidentialResult, str]:
        """Replace flagged sentence segments without exposing them in metadata."""
        result = self.scan(text, scan_target=scan_target)
        redacted = text
        for finding in reversed(result.findings):
            redacted = redacted[:finding.start] + finding.redacted_placeholder + redacted[finding.end:]
        logger.info("Confidential-information anonymization completed: %d segments redacted", result.finding_count)
        return result, redacted

    @staticmethod
    def _load_model() -> EmbeddingModel:
        try:
            from sentence_transformers import SentenceTransformer
            return SentenceTransformer(MODEL_NAME)
        except Exception as exc:
            logger.error("Confidential-information embedding model initialization failed")
            raise ConfidentialDetectorError(
                f"Embedding model unavailable. Install sentence-transformers and download {MODEL_NAME}."
            ) from exc

    def _encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        try:
            return self._model.encode(texts, normalize_embeddings=True)
        except Exception as exc:
            logger.error("Confidential-information embedding generation failed")
            raise ConfidentialDetectorError("Embedding generation could not be completed") from exc

    def _reference_texts(self) -> list[str]:
        return [phrase for details in self._config.semantic.values() for phrase in details["references"]]

    @staticmethod
    def _segments(text: str) -> list[tuple[str, int, int]]:
        segments: list[tuple[str, int, int]] = []
        cursor = 0
        for match in SENTENCE_BOUNDARY.finditer(text):
            ContextualConfidentialDetector._append_segment(segments, text, cursor, match.start())
            cursor = match.end()
        ContextualConfidentialDetector._append_segment(segments, text, cursor, len(text))
        return segments

    @staticmethod
    def _append_segment(segments: list[tuple[str, int, int]], text: str, start: int, end: int) -> None:
        raw = text[start:end]
        stripped = raw.strip()
        if stripped:
            offset = start + len(raw) - len(raw.lstrip())
            segments.append((stripped, offset, offset + len(stripped)))

    def _classify(self, segments: Sequence[tuple[str, int, int]], vectors: Sequence[Sequence[float]]) -> list[ConfidentialFinding]:
        categories = [category for category, details in self._config.semantic.items() for _ in details["references"]]
        findings: list[ConfidentialFinding] = []
        for (segment, start, end), vector in zip(segments, vectors):
            scores = [self._dot(vector, reference) for reference in self._reference_vectors]
            best_index, semantic_score = max(enumerate(scores), key=lambda item: item[1])
            category = categories[best_index]
            score, signals = self._hybrid_score(segment, category, semantic_score)
            if score >= self._threshold:
                findings.append(ConfidentialFinding(
                    category=category, start=start, end=end, score=round(float(score), 4),
                    threshold=self._threshold,
                    redacted_placeholder=f"<CONFIDENTIAL_INFORMATION:{category}>",
                    detection_method="HYBRID_SEMANTIC", signals=signals,
                ))
        return findings

    def _hybrid_score(self, segment: str, category: str, semantic_score: float) -> tuple[float, list[str]]:
        """Blend configured semantic, lexical, rule, and taxonomy evidence."""
        details = self._config.semantic[category]
        lowered = segment.casefold()
        keywords = details.get("keywords", ())
        negatives = details.get("negative_keywords", ())
        keyword_hits = [word for word in keywords if word.casefold() in lowered]
        negative_hits = [word for word in negatives if word.casefold() in lowered]
        taxonomy_terms = [
            term for aliases in (*self._config.organizations.values(), *self._config.projects.values(), *self._config.domain_terms.values())
            for term in aliases if term.casefold() in lowered
        ]
        rule_hits = [word for word in ("confidential", "unreleased", "non-public", "internal", "attached draft") if word in lowered]
        keyword_score = min(1.0, len(keyword_hits) / 2)
        rule_score = min(1.0, len(rule_hits) / 2)
        taxonomy_score = 1.0 if taxonomy_terms else 0.0
        weights = self._config.semantic_weights
        score = (
            weights.semantic * max(0.0, semantic_score)
            + weights.keywords * keyword_score
            + weights.rules * rule_score
            + weights.taxonomy * taxonomy_score
        )
        if negative_hits:
            score *= 0.45
        signals = ["semantic_similarity"]
        signals.extend(f"keyword:{item}" for item in keyword_hits)
        signals.extend(f"rule:{item}" for item in rule_hits)
        signals.extend(f"taxonomy:{item}" for item in taxonomy_terms)
        signals.extend(f"negative_context:{item}" for item in negative_hits)
        return min(1.0, score), signals

    @staticmethod
    def _dot(left: Sequence[float], right: Sequence[float]) -> float:
        return float(sum(a * b for a, b in zip(left, right)))

    @staticmethod
    def _validate_text(text: str) -> None:
        if not isinstance(text, str):
            raise ValueError("text must be a string")

    @staticmethod
    def _validate_target(scan_target: str) -> None:
        if scan_target not in {"prompt", "response"}:
            raise ValueError("scan_target must be 'prompt' or 'response'")


@lru_cache(maxsize=1)
def get_confidential_detector() -> ContextualConfidentialDetector:
    """Create the process-wide semantic detector lazily when its endpoint is used."""
    return ContextualConfidentialDetector()
