"""Hybrid, evidence-only bias detection for LLM responses.

This module reports bias evidence and an aggregated risk score. It never makes
ALLOW, BLOCK, or ESCALATE decisions; those remain PolicyEngine concerns.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, Sequence

from api.schemas import BiasBehavior, BiasResult, BiasType, ProtectedDimension
from engines.responsibility.bias_check.bias_fairness import FairnessTrigger
from engines.responsibility.bias_check.bias_llm_judge import (
    LLMBiasJudge,
    LLMBiasJudgeError,
    run_llm_judge,
)

logger = logging.getLogger(__name__)
CONFIG_PATH = Path(__file__).with_name("bias_config.json")
SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


class BiasDetectorError(RuntimeError):
    """Raised when required model inference or detector configuration fails."""


class Embeddings(Protocol):
    def encode(
        self, texts: Sequence[str], *, normalize_embeddings: bool
    ) -> Sequence[Sequence[float]]: ...


class ToxicityClassifier(Protocol):
    def __call__(self, text: str) -> Any: ...


class BiasDetector:
    """Combine explicit, classifier, semantic, and contextual evidence."""

    def __init__(
        self,
        *,
        config_path: Path | str = CONFIG_PATH,
        embedding_model: Embeddings | None = None,
        classifier: ToxicityClassifier | None = None,
        llm_judge: LLMBiasJudge | None = None,
        enable_llm_judge: bool | None = None,
    ) -> None:
        self.config = self._load_config(Path(config_path))
        self.patterns = [
            (re.compile(item["pattern"], re.IGNORECASE), item)
            for item in self.config["patterns"]
        ]
        self.model = embedding_model or self._load_embedding_model()
        self.classifier = classifier or self._load_classifier()
        self.fairness_trigger = FairnessTrigger(self.config)
        self.llm_judge = llm_judge
        self.llm_judge_enabled = (
            bool(llm_judge)
            if enable_llm_judge is None
            else enable_llm_judge
        )
        if enable_llm_judge is None and llm_judge is None:
            self.llm_judge_enabled = bool(self.config["llm_judge"]["enabled"])
        self.references = self.config["semantic_references"]
        self.reference_vectors = self._encode(
            [item["text"] for item in self.references]
        )

    def scan(self, text: str, *, scan_target: str = "response") -> BiasResult:
        """Return safe bias evidence for response text without policy action."""
        self._validate_input(text, scan_target)
        if not text:
            return BiasResult(detected=False, detection_method="HYBRID")

        segments = self._segments(text)
        fairness = self.fairness_trigger.detect(segments)
        explicit = self._explicit(segments)
        semantic = self._semantic(segments, fairness)
        toxicity, identity_hate = self._model_scores(text)
        evidence = fairness + explicit + semantic

        if toxicity >= self.config["model_threshold"]:
            evidence.append(
                {"signal": "TOXICITY_MODEL", "confidence": round(toxicity, 4)}
            )
        if identity_hate >= self.config["model_threshold"]:
            evidence.append(
                {
                    "signal": "IDENTITY_HATE_MODEL",
                    "confidence": round(identity_hate, 4),
                }
            )

        llm_used = False
        if self.llm_judge_enabled and self._should_call_llm(
            segments, fairness, explicit, semantic
        ):
            if self.llm_judge is None:
                raise BiasDetectorError("LLM bias judge is unavailable")
            candidate_dimensions = sorted(
                {
                    dimension
                    for item in fairness
                    for dimension in item["candidate_dimensions"]
                }
            )
            try:
                judgment = run_llm_judge(
                    self.llm_judge,
                    text,
                    candidate_dimensions=candidate_dimensions,
                    evidence=evidence,
                )
            except LLMBiasJudgeError as exc:
                raise BiasDetectorError(str(exc)) from exc
            llm_used = True
            if (
                judgment.endorses_bias
                and judgment.confidence >= self.config["llm_judge"]["minimum_confidence"]
            ):
                evidence.append(
                    {
                        "signal": "LLM_BIAS_JUDGE",
                        "protected_dimensions": list(judgment.protected_dimensions),
                        "behaviors": list(judgment.behaviors),
                        "confidence": round(judgment.confidence, 4),
                    }
                )
            elif judgment.endorses_bias:
                evidence.append(
                    {
                        "signal": "LLM_BIAS_JUDGE_LOW_CONFIDENCE",
                        "confidence": round(judgment.confidence, 4),
                    }
                )
            else:
                evidence.append(
                    {
                        "signal": "LLM_BIAS_JUDGE_SAFE",
                        "confidence": round(judgment.confidence, 4),
                    }
                )

        risk_score = self._aggregate(evidence, toxicity, identity_hate)
        dimensions = self._bias_dimensions(evidence)
        behaviors = self._bias_behaviors(evidence)
        detected = (
            risk_score >= self.config["final_detection_threshold"]
            and bool(dimensions)
        )

        return BiasResult(
            detected=detected,
            score=risk_score,
            risk_score=risk_score,
            protected_dimensions=[ProtectedDimension(item) for item in dimensions],
            behaviors=[BiasBehavior(item) for item in behaviors],
            bias_types=(
                [self._legacy_type(item) for item in dimensions if item in _LEGACY_TYPES]
                if detected
                else []
            ),
            evidence=evidence,
            toxicity_score=round(toxicity, 4),
            identity_hate_score=round(identity_hate, 4),
            confidence=risk_score,
            detection_method="HYBRID_LLM" if llm_used else "HYBRID",
            flagged_segments=[],
        )

    def _explicit(self, segments: Sequence[str]) -> list[dict[str, Any]]:
        threshold = self.config["explicit_pattern_threshold"]
        evidence: list[dict[str, Any]] = []
        for segment_index, segment in enumerate(segments):
            modifier = self._context_modifier(segment)
            for regex, pattern in self.patterns:
                confidence = float(pattern["confidence"])
                if confidence < threshold or not regex.search(segment):
                    continue
                evidence.append(
                    self._evidence(
                        "EXPLICIT_PATTERN",
                        pattern,
                        confidence,
                        segment_index,
                        modifier,
                    )
                )
        return evidence

    def _semantic(
        self,
        segments: Sequence[str],
        fairness: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fairness_by_segment = {
            item["segment_index"]: set(item["candidate_dimensions"])
            for item in fairness
        }
        candidates = [
            (index, segment)
            for index, segment in enumerate(segments)
            if index in fairness_by_segment or self._is_semantic_candidate(segment)
        ]
        if not candidates:
            return []

        vectors = self._encode([segment for _, segment in candidates])
        evidence: list[dict[str, Any]] = []
        threshold = self.config["semantic_threshold"]
        dimensions = sorted({item["dimension"] for item in self.references})

        for (segment_index, segment), vector in zip(candidates, vectors):
            modifier = self._context_modifier(segment)
            allowed_dimensions = fairness_by_segment.get(segment_index, set(dimensions))
            for dimension in sorted(allowed_dimensions):
                indexes = [
                    index
                    for index, item in enumerate(self.references)
                    if item["dimension"] == dimension
                ]
                scored = [
                    (index, self._dot(vector, self.reference_vectors[index]))
                    for index in indexes
                ]
                reference_index, score = max(scored, key=lambda item: item[1])
                if score < threshold:
                    continue
                reference = self.references[reference_index]
                evidence.append(
                    self._evidence(
                        "SEMANTIC_BIAS",
                        reference,
                        float(score),
                        segment_index,
                        modifier,
                        reference_id=reference["id"],
                    )
                )
        return evidence

    def _aggregate(
        self,
        evidence: Sequence[dict[str, Any]],
        toxicity: float,
        identity_hate: float,
    ) -> float:
        bias_signals = [
            float(item.get("adjusted_confidence", item["confidence"]))
            for item in evidence
            if item["signal"] in {"EXPLICIT_PATTERN", "SEMANTIC_BIAS", "LLM_BIAS_JUDGE"}
        ]
        if not bias_signals:
            return 0.0
        score = max(bias_signals)
        reinforcing_signals = sum(
            1
            for item in evidence
            if item["signal"]
            in {"EXPLICIT_PATTERN", "SEMANTIC_BIAS", "LLM_BIAS_JUDGE"}
            and float(item.get("adjusted_confidence", item["confidence"]))
            >= self.config["weak_signal_threshold"]
        )
        if reinforcing_signals > 1:
            score += self.config["reinforcement_increment"] * (
                reinforcing_signals - 1
            )
        supporting_model_score = max(toxicity, identity_hate)
        if supporting_model_score >= self.config["model_threshold"]:
            score += (
                self.config["toxicity_support_increment"]
                * supporting_model_score
            )
        safe_judgments = [
            float(item["confidence"])
            for item in evidence
            if item["signal"] == "LLM_BIAS_JUDGE_SAFE"
        ]
        if safe_judgments:
            score *= 1.0 - (
                max(safe_judgments) * self.config["llm_safe_reduction"]
            )
        return round(max(0.0, min(1.0, score)), 4)

    def _model_scores(self, text: str) -> tuple[float, float]:
        try:
            output = self.classifier(text)
        except Exception as exc:
            raise BiasDetectorError("Toxicity classifier inference failed") from exc

        rows = (
            output[0]
            if isinstance(output, list) and output and isinstance(output[0], list)
            else output
        )
        rows = rows if isinstance(rows, list) else [rows]
        values = {
            str(item.get("label", "")).upper(): float(item.get("score", 0.0))
            for item in rows
            if isinstance(item, dict)
        }
        toxicity = max(
            (
                value
                for label, value in values.items()
                if any(name in label for name in ("TOXIC", "HATE", "INSULT"))
            ),
            default=0.0,
        )
        identity_hate = max(
            (value for label, value in values.items() if "IDENTITY_HATE" in label),
            default=0.0,
        )
        return toxicity, identity_hate

    def _should_call_llm(
        self,
        segments: Sequence[str],
        fairness: Sequence[dict[str, Any]],
        explicit: Sequence[dict[str, Any]],
        semantic: Sequence[dict[str, Any]],
    ) -> bool:
        """Route difficult fairness cases without relying on a score range."""
        if not fairness:
            return False
        candidate_dimensions = {
            dimension
            for item in fairness
            for dimension in item["candidate_dimensions"]
        }
        explicit_dimensions = {item["dimension"] for item in explicit}
        semantic_dimensions = {item["dimension"] for item in semantic}
        established_dimensions = explicit_dimensions | semantic_dimensions
        fairness_segments = {item["segment_index"] for item in fairness}
        ambiguous_context = any(
            self._context_modifier(segment) < 0.0
            for index, segment in enumerate(segments)
            if index in fairness_segments
        )
        no_bias_evidence = not explicit and not semantic
        uncovered_dimension = bool(candidate_dimensions - established_dimensions)
        signal_disagreement = bool(explicit or semantic) and (
            explicit_dimensions != semantic_dimensions
        )
        return (
            no_bias_evidence
            or uncovered_dimension
            or signal_disagreement
            or ambiguous_context
        )

    @staticmethod
    def _bias_dimensions(evidence: Sequence[dict[str, Any]]) -> list[str]:
        dimensions: set[str] = set()
        for item in evidence:
            if item["signal"] not in {
                "EXPLICIT_PATTERN", "SEMANTIC_BIAS", "LLM_BIAS_JUDGE"
            }:
                continue
            if "dimension" in item:
                dimensions.add(item["dimension"])
            dimensions.update(item.get("protected_dimensions", []))
        return sorted(dimensions)

    @staticmethod
    def _bias_behaviors(evidence: Sequence[dict[str, Any]]) -> list[str]:
        behaviors: set[str] = set()
        for item in evidence:
            if item["signal"] not in {
                "EXPLICIT_PATTERN", "SEMANTIC_BIAS", "LLM_BIAS_JUDGE"
            }:
                continue
            if "behavior" in item:
                behaviors.add(item["behavior"])
            behaviors.update(item.get("behaviors", []))
        return sorted(behaviors)

    def _context_modifier(self, text: str) -> float:
        lowered = text.casefold()
        reporting_quote = ("'" in text or '"' in text) and any(
            term in lowered
            for term in ("example", "statement", "generated", "identified", "quoted")
        )
        anti_bias = bool(
            re.search(
                r"(?:do not|don't|should not)\s+(?:reject|exclude|discriminate against)\b"
                r".*\b(?:because of|based on)\b",
                lowered,
            )
        )
        configured = any(
            term.casefold() in lowered for term in self.config["context_modifiers"]
        )
        return -float(self.config["context_reduction"]) if (
            reporting_quote or anti_bias or configured
        ) else 0.0

    def _is_semantic_candidate(self, text: str) -> bool:
        lowered = text.casefold()
        return any(
            re.search(pattern, lowered)
            for pattern in self.config["semantic_candidate_patterns"]
        )

    def _evidence(
        self,
        signal: str,
        source: dict[str, Any],
        confidence: float,
        segment_index: int,
        context_modifier: float,
        *,
        reference_id: str | None = None,
    ) -> dict[str, Any]:
        adjusted = confidence * (1.0 + context_modifier)
        result: dict[str, Any] = {
            "signal": signal,
            "dimension": source["dimension"],
            "behavior": source["behavior"],
            "confidence": round(confidence, 4),
            "adjusted_confidence": round(max(0.0, adjusted), 4),
            "context_modifier": round(context_modifier, 4),
            "segment_index": segment_index,
        }
        if reference_id is not None:
            result["reference_id"] = reference_id
        return result

    def _encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        try:
            return self.model.encode(texts, normalize_embeddings=True)
        except Exception as exc:
            raise BiasDetectorError("Bias embedding generation failed") from exc

    def _load_embedding_model(self) -> Embeddings:
        try:
            from sentence_transformers import SentenceTransformer

            return SentenceTransformer(self.config["semantic_model_name"])
        except Exception as exc:
            raise BiasDetectorError("Bias embedding model is unavailable") from exc

    def _load_classifier(self) -> ToxicityClassifier:
        try:
            from transformers import pipeline

            return pipeline(
                "text-classification",
                model=self.config["model_name"],
                top_k=None,
            )
        except Exception as exc:
            raise BiasDetectorError("Toxicity classifier is unavailable") from exc

    @staticmethod
    def _segments(text: str) -> list[str]:
        return [segment.strip() for segment in SENTENCE_BOUNDARY.split(text) if segment.strip()]

    @staticmethod
    def _dot(left: Sequence[float], right: Sequence[float]) -> float:
        return float(sum(a * b for a, b in zip(left, right)))

    @staticmethod
    def _validate_input(text: str, scan_target: str) -> None:
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        if scan_target != "response":
            raise ValueError("scan_target must be 'response'")

    @staticmethod
    def _load_config(path: Path) -> dict[str, Any]:
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            required = {
                "model_name", "semantic_model_name", "explicit_pattern_threshold",
                "model_threshold", "semantic_threshold", "final_detection_threshold",
                "context_reduction", "toxicity_support_increment",
                "llm_safe_reduction", "weak_signal_threshold",
                "reinforcement_increment", "patterns", "semantic_references",
                "semantic_candidate_patterns", "context_modifiers",
                "fairness_trigger", "llm_judge",
            }
            if not required.issubset(config):
                raise ValueError("missing required keys")
            for key in (
                "explicit_pattern_threshold", "model_threshold", "semantic_threshold",
                "final_detection_threshold", "context_reduction",
                "toxicity_support_increment", "llm_safe_reduction",
                "weak_signal_threshold", "reinforcement_increment",
            ):
                if not 0.0 <= float(config[key]) <= 1.0:
                    raise ValueError(f"invalid {key}")
            return config
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise BiasDetectorError("Bias detector configuration is invalid") from exc

    @staticmethod
    def _legacy_type(dimension: str) -> BiasType:
        return _LEGACY_TYPES[dimension]


_LEGACY_TYPES = {
    "GENDER": BiasType.GENDER_BIAS,
    "AGE": BiasType.AGE_BIAS,
    "RELIGION": BiasType.RELIGIOUS_BIAS,
    "DISABILITY": BiasType.DISABILITY_BIAS,
    "SOCIOECONOMIC_STATUS": BiasType.SOCIOECONOMIC_BIAS,
    "RACE_ETHNICITY": BiasType.RACIAL_BIAS,
}


@lru_cache(maxsize=1)
def get_bias_detector() -> BiasDetector:
    """Load models and reference embeddings once per application process."""
    return BiasDetector()
