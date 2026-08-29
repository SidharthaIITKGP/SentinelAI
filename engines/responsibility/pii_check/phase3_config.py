"""Central configuration for the additive Phase 3 detector upgrades."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final


DEFAULT_TAXONOMY_PATH: Final = Path(__file__).with_name("config") / "phase3_taxonomy.json"


@dataclass(frozen=True)
class EntropyConfig:
    minimum_length: int = 16
    minimum_entropy: float = 3.5
    context_terms: tuple[str, ...] = (
        "api_key", "api key", "apikey", "api-token", "token", "access_token", "access token",
        "secret", "client_secret", "client secret", "password", "passwd", "credential", "auth", "bearer",
    )
    allowlist: frozenset[str] = frozenset({"TEST_VALUE_ALLOWED_12345"})


@dataclass(frozen=True)
class SemanticWeights:
    """Weights sum to one: semantic evidence remains the primary signal."""
    semantic: float = 0.60
    keywords: float = 0.20
    rules: float = 0.10
    taxonomy: float = 0.10


@dataclass(frozen=True)
class Phase3Config:
    taxonomy_path: Path
    organizations: dict[str, tuple[str, ...]]
    people: dict[str, tuple[str, ...]]
    projects: dict[str, tuple[str, ...]]
    domain_terms: dict[str, tuple[str, ...]]
    semantic: dict[str, dict[str, tuple[str, ...]]]
    entropy: EntropyConfig = field(default_factory=EntropyConfig)
    semantic_weights: SemanticWeights = field(default_factory=SemanticWeights)
    # With semantic weight 0.60, this accepts a near-perfect semantic match
    # while still requiring additional evidence for weaker matches.
    semantic_threshold: float = 0.55


def load_phase3_config(taxonomy_path: str | Path | None = None) -> Phase3Config:
    """Load organization taxonomy from configured local JSON; never from a service."""
    resolved = Path(taxonomy_path or os.getenv("SENTINELAI_PHASE3_TAXONOMY_PATH", DEFAULT_TAXONOMY_PATH))
    with resolved.open(encoding="utf-8") as file:
        raw = json.load(file)
    normalize = lambda values: tuple(str(value) for value in values)
    return Phase3Config(
        taxonomy_path=resolved,
        organizations={key: normalize(values) for key, values in raw.get("organizations", {}).items()},
        people={key: normalize(values) for key, values in raw.get("people", {}).items()},
        projects={key: normalize(values) for key, values in raw.get("projects", {}).items()},
        domain_terms={key: normalize(values) for key, values in raw.get("domain_terms", {}).items()},
        semantic={
            category: {key: normalize(values) for key, values in details.items()}
            for category, details in raw.get("semantic", {}).items()
        },
    )
