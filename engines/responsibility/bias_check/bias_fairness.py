"""Non-decisive fairness trigger for routing potentially sensitive decisions."""

from __future__ import annotations

import re
from typing import Any, Sequence


class FairnessTrigger:
    """Find protected-group plus decision/treatment language without declaring bias."""

    def __init__(self, config: dict[str, Any]) -> None:
        trigger = config["fairness_trigger"]
        self._groups = {
            dimension: tuple(term.casefold() for term in terms)
            for dimension, terms in trigger["protected_group_terms"].items()
        }
        self._decision_patterns = self._compile(trigger["decision_patterns"])
        self._treatment_patterns = self._compile(trigger["treatment_patterns"])

    def detect(self, segments: Sequence[str]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for segment_index, segment in enumerate(segments):
            lowered = segment.casefold()
            dimensions = [
                dimension
                for dimension, terms in self._groups.items()
                if any(self._contains_term(lowered, term) for term in terms)
            ]
            decision_signals = self._matches(lowered, self._decision_patterns)
            treatment_signals = self._matches(lowered, self._treatment_patterns)
            if dimensions and decision_signals and treatment_signals:
                evidence.append(
                    {
                        "signal": "FAIRNESS_TRIGGER",
                        "candidate_dimensions": sorted(dimensions),
                        "decision_signals": decision_signals,
                        "treatment_signals": treatment_signals,
                        "confidence": 0.5,
                        "segment_index": segment_index,
                    }
                )
        return evidence

    @staticmethod
    def _compile(items: Sequence[dict[str, str]]) -> tuple[tuple[str, re.Pattern[str]], ...]:
        return tuple(
            (item["id"], re.compile(item["pattern"], re.IGNORECASE))
            for item in items
        )

    @staticmethod
    def _matches(
        text: str, patterns: Sequence[tuple[str, re.Pattern[str]]]
    ) -> list[str]:
        return [identifier for identifier, pattern in patterns if pattern.search(text)]

    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text))
