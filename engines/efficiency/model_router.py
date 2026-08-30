"""Deterministic, capability-first model routing and efficiency evaluation."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from api.schemas import (
    ComplexityAssessment,
    ComplexityLevel,
    EfficiencyResult,
    ModelProfile,
    ModelTier,
    RiskLevel,
    RoutingResult,
    UseCase,
)

logger = logging.getLogger("sentinelai.model_router")

MODEL_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"
TIER_ORDER = {
    ModelTier.ECONOMY: 0,
    ModelTier.STANDARD: 1,
    ModelTier.PREMIUM: 2,
}


def _normalize_risk(risk_level: RiskLevel | str) -> RiskLevel:
    try:
        return RiskLevel(str(getattr(risk_level, "value", risk_level)).upper())
    except ValueError:
        return RiskLevel.LOW


def _normalize_use_case(use_case: UseCase | str) -> UseCase:
    try:
        return UseCase(str(getattr(use_case, "value", use_case)).lower())
    except ValueError:
        return UseCase.CUSTOMER_CHATBOT


def load_model_registry(
    path: Path | str = MODEL_REGISTRY_PATH,
) -> tuple[list[ModelProfile], str, dict[str, int]]:
    """Load and validate the local estimated model registry."""
    registry_path = Path(path)
    with registry_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    profiles = [ModelProfile(**item) for item in raw.get("models", [])]
    ids = [profile.id for profile in profiles]
    if not profiles or len(ids) != len(set(ids)):
        raise ValueError("Model registry requires at least one uniquely identified profile")
    baseline_id = str(raw.get("baseline_profile_id", "standard"))
    if baseline_id not in ids:
        raise ValueError("Configured baseline profile is missing from model registry")
    budgets = {
        str(key): int(value)
        for key, value in (raw.get("latency_budgets_ms") or {}).items()
    }
    return profiles, baseline_id, budgets


def estimate_tokens(text: str) -> int:
    """Approximate tokens deterministically as ceil(non-whitespace characters / 4)."""
    character_count = len(re.sub(r"\s", "", text or ""))
    return (character_count + 3) // 4


def estimate_complexity(
    prompt: str,
    use_case: UseCase | str,
    risk_level: RiskLevel | str,
    *,
    estimated_input_tokens: Optional[int] = None,
) -> ComplexityAssessment:
    """Estimate explainable complexity without making another model call."""
    use_case = _normalize_use_case(use_case)
    risk_level = _normalize_risk(risk_level)
    tokens = estimate_tokens(prompt) if estimated_input_tokens is None else estimated_input_tokens
    if tokens < 0:
        raise ValueError("estimated_input_tokens cannot be negative")

    score = 0
    reasons: list[str] = []
    if tokens >= 2000:
        score += 3
        reasons.append("very_long_prompt")
    elif tokens >= 600:
        score += 2
        reasons.append("long_prompt")
    elif tokens >= 120:
        score += 1
        reasons.append("moderate_prompt_length")

    questions = (prompt or "").count("?")
    if questions >= 3:
        score += 2
        reasons.append("multiple_questions")
    elif questions == 2:
        score += 1
        reasons.append("two_questions")

    reasoning_terms = re.findall(
        r"\b(?:analy[sz]e|compare|reason|trade-?off|forecast|calculate|"
        r"explain why|step by step|scenario|recommend)\b",
        (prompt or "").lower(),
    )
    if len(reasoning_terms) >= 2:
        score += 2
        reasons.append("reasoning_heavy_terms")
    elif reasoning_terms:
        score += 1
        reasons.append("reasoning_term")

    if re.search(
        r"```|\{[^{}]+\}|\[[^\[\]]+\]|\bSELECT\b|\bdef\s+\w+",
        prompt or "",
        re.I,
    ):
        score += 1
        reasons.append("structured_or_code_like_content")

    if risk_level == RiskLevel.HIGH:
        score += 2
        reasons.append("high_risk_governance")
    elif risk_level == RiskLevel.MEDIUM:
        score += 1
        reasons.append("medium_risk_governance")

    if use_case == UseCase.FINANCE_TOOL:
        score += 1
        reasons.append("finance_domain")
    elif use_case == UseCase.HR_COPILOT and risk_level != RiskLevel.LOW:
        score += 1
        reasons.append("sensitive_hr_domain")

    level = (
        ComplexityLevel.LOW
        if score <= 1
        else ComplexityLevel.MEDIUM
        if score <= 3
        else ComplexityLevel.HIGH
    )
    return ComplexityAssessment(
        level=level,
        score=score,
        estimated_input_tokens=tokens,
        reasons=reasons or ["short_single_task"],
    )


def calculate_estimated_cost(
    profile: ModelProfile,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate a non-negative estimate; this is not provider billing."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts cannot be negative")
    cost = (
        input_tokens * profile.input_cost_per_1m_tokens
        + output_tokens * profile.output_cost_per_1m_tokens
    ) / 1_000_000
    return round(cost, 10)


def _capability_required(
    risk_level: RiskLevel,
    use_case: UseCase,
    complexity: ComplexityLevel,
) -> float:
    required = {
        RiskLevel.LOW: 0.45,
        RiskLevel.MEDIUM: 0.70,
        RiskLevel.HIGH: 0.90,
    }[risk_level]
    if use_case == UseCase.FINANCE_TOOL:
        required += 0.04
    elif use_case == UseCase.HR_COPILOT:
        required += 0.02
    complexity_floor = {
        ComplexityLevel.LOW: 0.45,
        ComplexityLevel.MEDIUM: 0.68,
        ComplexityLevel.HIGH: 0.82,
    }[complexity]
    return round(min(1.0, max(required, complexity_floor)), 2)


def _estimated_output_tokens(complexity: ComplexityLevel) -> int:
    return {
        ComplexityLevel.LOW: 128,
        ComplexityLevel.MEDIUM: 256,
        ComplexityLevel.HIGH: 512,
    }[complexity]


def _profile_supports(
    profile: ModelProfile,
    use_case: UseCase,
    risk_level: RiskLevel,
    required_capability: float,
    total_tokens: int,
) -> bool:
    return (
        profile.enabled
        and use_case in profile.supported_use_cases
        and risk_level in profile.supported_risk_levels
        and profile.capability_score >= required_capability
        and total_tokens <= profile.context_window
    )


def route_model(
    risk_level: RiskLevel | str,
    use_case: UseCase | str,
    prompt: str = "",
    *,
    latency_budget_ms: Optional[int] = None,
    estimated_input_tokens: Optional[int] = None,
    estimated_output_tokens: Optional[int] = None,
    profiles: Optional[list[ModelProfile]] = None,
    baseline_profile_id: Optional[str] = None,
) -> RoutingResult:
    """Select the least-cost safe profile, with capability ahead of latency/cost."""
    risk_level = _normalize_risk(risk_level)
    use_case = _normalize_use_case(use_case)
    registry_profiles, configured_baseline, budgets = load_model_registry()
    profiles = list(profiles) if profiles is not None else registry_profiles
    baseline_profile_id = baseline_profile_id or configured_baseline
    if not any(profile.enabled for profile in profiles):
        raise RuntimeError("No enabled model profiles are available")

    complexity = estimate_complexity(
        prompt,
        use_case,
        risk_level,
        estimated_input_tokens=estimated_input_tokens,
    )
    input_tokens = complexity.estimated_input_tokens
    output_tokens = (
        _estimated_output_tokens(complexity.level)
        if estimated_output_tokens is None
        else estimated_output_tokens
    )
    if output_tokens < 0:
        raise ValueError("estimated_output_tokens cannot be negative")
    total_tokens = input_tokens + output_tokens
    required = _capability_required(risk_level, use_case, complexity.level)

    budget = (
        latency_budget_ms
        if latency_budget_ms is not None
        else budgets.get(str(use_case.value), 700)
    )
    if budget <= 0:
        raise ValueError("latency_budget_ms must be positive")

    baseline = next(
        (profile for profile in profiles if profile.id == baseline_profile_id),
        None,
    )
    if baseline is None:
        raise ValueError("Baseline profile is not present in supplied profiles")

    safe_candidates = [
        profile
        for profile in profiles
        if _profile_supports(profile, use_case, risk_level, required, total_tokens)
    ]
    within_budget = [
        profile for profile in safe_candidates if profile.expected_latency_ms <= budget
    ]
    constraints_unmet: list[str] = []

    def projected_cost(profile: ModelProfile) -> float:
        return calculate_estimated_cost(profile, input_tokens, output_tokens)

    if within_budget:
        selected = min(
            within_budget,
            key=lambda profile: (
                projected_cost(profile),
                profile.expected_latency_ms,
                TIER_ORDER[ModelTier(profile.tier)],
            ),
        )
        reason = (
            "Selected the lowest estimated-cost profile satisfying capability, "
            "policy, context, and latency constraints."
        )
    elif safe_candidates:
        selected = min(
            safe_candidates,
            key=lambda profile: (profile.expected_latency_ms, projected_cost(profile)),
        )
        constraints_unmet.append("latency_budget")
        reason = (
            "No safe model meets the latency budget; capability and policy were "
            "preserved, so the latency breach is explicit."
        )
    else:
        eligible = [
            profile
            for profile in profiles
            if profile.enabled and use_case in profile.supported_use_cases
        ]
        if not eligible:
            eligible = [profile for profile in profiles if profile.enabled]
            constraints_unmet.append("use_case_support")
        selected = max(
            eligible,
            key=lambda profile: (
                profile.capability_score,
                profile.context_window,
                -profile.expected_latency_ms,
            ),
        )
        if risk_level not in selected.supported_risk_levels:
            constraints_unmet.append("risk_policy")
        if selected.capability_score < required:
            constraints_unmet.append("capability_requirement")
        if total_tokens > selected.context_window:
            constraints_unmet.append("context_window")
        if selected.expected_latency_ms > budget:
            constraints_unmet.append("latency_budget")
        reason = (
            "No profile satisfies every hard constraint; selected the highest-"
            "capability enabled route and reported every unmet constraint."
        )

    selected_cost = projected_cost(selected)
    baseline_cost = projected_cost(baseline)
    savings = round(baseline_cost - selected_cost, 10)
    savings_percent = (
        round((savings / baseline_cost) * 100, 4) if baseline_cost > 0 else 0.0
    )
    capability_met = selected.capability_score >= required
    context_sufficient = total_tokens <= selected.context_window
    latency_breached = selected.expected_latency_ms > budget
    if risk_level == RiskLevel.HIGH:
        reason += " High-risk governance forbids capability downgrade for speed or savings."

    result = RoutingResult(
        model=selected.provider_model,
        max_tokens=selected.max_output_tokens,
        temperature={
            RiskLevel.LOW: 0.3,
            RiskLevel.MEDIUM: 0.2,
            RiskLevel.HIGH: 0.1,
        }[risk_level],
        reason=reason,
        estimated_cost_usd=selected_cost,
        selected_model=selected.provider_model,
        selected_profile_id=selected.id,
        selected_tier=selected.tier,
        baseline_model=baseline.provider_model,
        baseline_profile_id=baseline.id,
        routing_reason=reason,
        complexity=complexity,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        baseline_estimated_cost_usd=baseline_cost,
        estimated_savings_usd=savings,
        estimated_savings_percent=savings_percent,
        expected_latency_ms=selected.expected_latency_ms,
        latency_budget_ms=budget,
        latency_budget_breached=latency_breached,
        capability_required=required,
        capability_selected=selected.capability_score,
        capability_requirement_met=capability_met,
        context_window_sufficient=context_sufficient,
        constraints_unmet=constraints_unmet,
        profile_values_are_estimated=selected.estimated_profile,
    )
    logger.info(
        "Model routed | risk=%s | use_case=%s | tier=%s | model=%s | cost_estimate=%.8f",
        risk_level.value,
        use_case.value,
        result.selected_tier,
        result.selected_model,
        selected_cost,
    )
    return result


def routing_from_model_config(
    config: Any,
    risk_level: RiskLevel | str,
    use_case: UseCase | str,
    prompt: str,
) -> RoutingResult:
    """Adapt legacy test/plugin ModelConfig values without breaking the pipeline."""
    if isinstance(config, RoutingResult):
        return config
    get = (
        config.get
        if isinstance(config, dict)
        else lambda key, default=None: getattr(config, key, default)
    )
    model = str(get("model", "groq/openai/gpt-oss-120b"))
    complexity = estimate_complexity(prompt, use_case, risk_level)
    estimated_cost = float(get("estimated_cost_usd", 0.0) or 0.0)
    reason = str(get("reason", "Legacy model configuration"))
    return RoutingResult(
        model=model,
        max_tokens=int(get("max_tokens", 500)),
        temperature=float(get("temperature", 0.3)),
        reason=reason,
        estimated_cost_usd=estimated_cost,
        selected_model=model,
        selected_profile_id="legacy",
        selected_tier=ModelTier.STANDARD,
        baseline_model=model,
        baseline_profile_id="legacy",
        routing_reason=reason,
        complexity=complexity,
        estimated_input_tokens=complexity.estimated_input_tokens,
        estimated_output_tokens=int(get("max_tokens", 500)),
        baseline_estimated_cost_usd=estimated_cost,
        estimated_savings_usd=0.0,
        estimated_savings_percent=0.0,
        expected_latency_ms=500,
        latency_budget_ms=700,
        latency_budget_breached=False,
        capability_required=1.0,
        capability_selected=1.0,
        capability_requirement_met=True,
        context_window_sufficient=True,
        profile_values_are_estimated=True,
    )


def evaluate_efficiency(
    routing: RoutingResult,
    *,
    actual_latency_ms: Optional[int] = None,
    retry_count: int = 0,
) -> EfficiencyResult:
    """Balance model fit, estimated cost, and latency; cheapest is not sufficient."""
    if actual_latency_ms is not None and actual_latency_ms < 0:
        raise ValueError("actual_latency_ms cannot be negative")
    if retry_count < 0:
        raise ValueError("retry_count cannot be negative")
    fit_score = min(
        1.0,
        routing.capability_selected / routing.capability_required
        if routing.capability_required > 0
        else 1.0,
    )
    selected_cost = float(routing.estimated_cost_usd or 0.0)
    baseline_cost = routing.baseline_estimated_cost_usd
    cost_score = 1.0 if selected_cost == 0 else min(1.0, baseline_cost / selected_cost)
    latency_value = (
        actual_latency_ms
        if actual_latency_ms is not None
        else routing.expected_latency_ms
    )
    latency_score = min(1.0, routing.latency_budget_ms / max(1, latency_value))
    overall = 0.50 * fit_score + 0.25 * cost_score + 0.25 * latency_score
    if not routing.capability_requirement_met:
        # Capability is a safety gate, not a peer that cheapness can offset.
        overall = min(overall, fit_score * 0.60)
    latency_breached = (
        routing.latency_budget_breached
        or (actual_latency_ms is not None and actual_latency_ms > routing.latency_budget_ms)
    )
    explanations = [routing.routing_reason]
    if routing.estimated_savings_usd < 0:
        explanations.append(
            "Estimated savings are negative because governance selected a stronger "
            "model than the baseline."
        )
    if latency_breached:
        explanations.append(
            "Measured or expected latency exceeds budget; capability constraints "
            "were not weakened."
        )
    if not routing.capability_requirement_met:
        explanations.append("No enabled profile fully met the capability requirement.")
    return EfficiencyResult(
        model_fit_score=round(fit_score, 4),
        cost_score=round(cost_score, 4),
        latency_score=round(latency_score, 4),
        overall_efficiency_score=round(max(0.0, min(1.0, overall)), 4),
        selected_model=routing.selected_model,
        selected_tier=routing.selected_tier,
        baseline_model=routing.baseline_model,
        estimated_cost_usd=selected_cost,
        baseline_estimated_cost_usd=baseline_cost,
        estimated_savings_usd=routing.estimated_savings_usd,
        estimated_savings_percent=routing.estimated_savings_percent,
        expected_latency_ms=routing.expected_latency_ms,
        actual_latency_ms=actual_latency_ms,
        latency_budget_ms=routing.latency_budget_ms,
        latency_budget_breached=latency_breached,
        capability_required=routing.capability_required,
        capability_selected=routing.capability_selected,
        capability_requirement_met=routing.capability_requirement_met,
        retry_count=retry_count,
        explanation=explanations,
        values_are_estimated=routing.profile_values_are_estimated,
    )
