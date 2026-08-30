"""Adversarial Phase 3 routing, cost, latency, and integration tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

import core.pipeline as pipeline
from api.schemas import (
    ActionType,
    BiasResult,
    ComplexityLevel,
    GroundednessResult,
    GroundednessVerdict,
    InjectionResult,
    InterceptRequest,
    ModelProfile,
    ModelTier,
    PIIResult,
    PolicyDecision,
    RiskLevel,
    UseCase,
)
from engines.efficiency.model_router import (
    calculate_estimated_cost,
    estimate_complexity,
    estimate_tokens,
    evaluate_efficiency,
    load_model_registry,
    route_model,
)


def _profiles() -> list[ModelProfile]:
    profiles, _, _ = load_model_registry()
    return [profile.model_copy(deep=True) for profile in profiles]


def _profile(profile_id: str) -> ModelProfile:
    return next(profile for profile in _profiles() if profile.id == profile_id)


def _patch_pipeline_for_routing(
    monkeypatch,
    llm_mock: AsyncMock,
    risk_level: RiskLevel,
) -> None:
    async def clean_injection(prompt: str):
        return InjectionResult(detected=False)

    async def clean_pii(text: str, scan_target: str = "prompt"):
        return PIIResult(found=False, scan_target=scan_target)

    async def clean_bias(text: str):
        return BiasResult(detected=False)

    async def supported(response: str, use_case: UseCase):
        return GroundednessResult(
            verdict=GroundednessVerdict.SUPPORTED,
            score=1.0,
            total_claims_checked=1,
            grounded_claims_count=1,
            use_case_kb_used=use_case,
        )

    async def allow_policy(**kwargs):
        return PolicyDecision(
            approved=True,
            final_action=ActionType.ALLOW,
            reason="clean",
            policy_file="tests/policy",
            threshold_applied=0.2,
        )

    monkeypatch.setattr(pipeline, "injection_scan", clean_injection)
    monkeypatch.setattr(pipeline, "detect_pii", clean_pii)
    monkeypatch.setattr(pipeline, "detect_bias", clean_bias)
    monkeypatch.setattr(pipeline, "scan_toxic_content", None)
    monkeypatch.setattr(pipeline, "groundedness_check", supported)
    monkeypatch.setattr(pipeline, "_call_llm", llm_mock)
    monkeypatch.setattr(pipeline, "evaluate_policy", allow_policy)
    monkeypatch.setattr(pipeline, "_classify_risk", lambda **kwargs: risk_level)


def _request(use_case: UseCase) -> InterceptRequest:
    return InterceptRequest(
        prompt="Review this request safely.",
        use_case=use_case,
        tenant_id="tenant-routing-correction",
        user_id="user-routing-correction",
    )


def test_registry_has_three_materially_distinct_estimated_tiers() -> None:
    profiles, baseline, budgets = load_model_registry()
    assert {profile.tier for profile in profiles} == {
        ModelTier.ECONOMY,
        ModelTier.STANDARD,
        ModelTier.PREMIUM,
    }
    assert len({profile.provider_model for profile in profiles}) == 3
    assert len({profile.capability_score for profile in profiles}) == 3
    assert all(profile.estimated_profile for profile in profiles)
    assert baseline == "standard"
    assert budgets[UseCase.CUSTOMER_CHATBOT.value] < budgets[UseCase.FINANCE_TOOL.value]


def test_simple_low_risk_customer_request_uses_economy() -> None:
    result = route_model(RiskLevel.LOW, UseCase.CUSTOMER_CHATBOT, "Where is my order?")
    assert result.selected_tier == ModelTier.ECONOMY
    assert result.capability_requirement_met
    assert result.estimated_savings_usd > 0


def test_medium_reasoning_request_uses_standard() -> None:
    result = route_model(
        RiskLevel.MEDIUM,
        UseCase.CUSTOMER_CHATBOT,
        "Compare both return options and recommend the safer choice?",
    )
    assert result.selected_tier == ModelTier.STANDARD
    assert result.complexity.level == ComplexityLevel.MEDIUM


def test_high_risk_finance_rejects_cheapest_model() -> None:
    result = route_model(
        RiskLevel.HIGH,
        UseCase.FINANCE_TOOL,
        "Approve this transfer?",
    )
    assert result.selected_tier == ModelTier.PREMIUM
    assert result.capability_selected >= result.capability_required
    assert result.estimated_savings_usd < 0
    assert "forbids capability downgrade" in result.routing_reason


def test_high_risk_hr_enforces_capability_despite_short_prompt() -> None:
    result = route_model(
        RiskLevel.HIGH,
        UseCase.HR_COPILOT,
        "Terminate them?",
    )
    assert result.estimated_input_tokens < 10
    assert result.selected_tier == ModelTier.PREMIUM
    assert result.capability_requirement_met


def test_long_low_risk_prompt_accounts_for_size_without_automatically_using_premium() -> None:
    result = route_model(
        RiskLevel.LOW,
        UseCase.CUSTOMER_CHATBOT,
        "ordinary shipping details " * 600,
    )
    assert result.complexity.level == ComplexityLevel.MEDIUM
    assert result.selected_tier == ModelTier.STANDARD


def test_tight_latency_low_risk_prefers_fast_safe_economy() -> None:
    result = route_model(
        RiskLevel.LOW,
        UseCase.CUSTOMER_CHATBOT,
        "Track order",
        latency_budget_ms=250,
    )
    assert result.selected_tier == ModelTier.ECONOMY
    assert result.latency_budget_breached is False


def test_tight_latency_high_risk_records_breach_instead_of_downgrade() -> None:
    result = route_model(
        RiskLevel.HIGH,
        UseCase.FINANCE_TOOL,
        "Approve transfer?",
        latency_budget_ms=200,
    )
    assert result.selected_tier == ModelTier.PREMIUM
    assert result.latency_budget_breached is True
    assert "latency_budget" in result.unmet_constraints
    assert result.generation_approved is True


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (119, ComplexityLevel.LOW),
        (120, ComplexityLevel.LOW),
        (599, ComplexityLevel.LOW),
        (600, ComplexityLevel.MEDIUM),
        (1999, ComplexityLevel.MEDIUM),
        (2000, ComplexityLevel.MEDIUM),
    ],
)
def test_complexity_token_boundaries_are_stable(tokens, expected) -> None:
    result = estimate_complexity(
        "single task",
        UseCase.CUSTOMER_CHATBOT,
        RiskLevel.LOW,
        estimated_input_tokens=tokens,
    )
    assert result.level == expected


def test_multiple_reasoning_signals_cross_high_complexity_boundary() -> None:
    result = estimate_complexity(
        "Analyze and compare these scenarios. Why? What changes? Recommend one?",
        UseCase.CUSTOMER_CHATBOT,
        RiskLevel.LOW,
        estimated_input_tokens=100,
    )
    assert result.level == ComplexityLevel.HIGH
    assert "multiple_questions" in result.reasons
    assert "reasoning_heavy_terms" in result.reasons


def test_token_estimator_is_deterministic_and_ignores_whitespace() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a b c d") == 1
    assert estimate_tokens("") == 0


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens"),
    [(0, 0), (0, 5000), (5_000_000, 1), (20, 2000)],
)
def test_cost_edge_cases_follow_formula_and_never_go_negative(
    input_tokens, output_tokens
) -> None:
    profile = _profile("standard")
    cost = calculate_estimated_cost(profile, input_tokens, output_tokens)
    expected = round(
        (
            input_tokens * profile.input_cost_per_1m_tokens
            + output_tokens * profile.output_cost_per_1m_tokens
        )
        / 1_000_000,
        10,
    )
    assert cost == expected
    assert cost >= 0


def test_negative_token_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        calculate_estimated_cost(_profile("economy"), -1, 10)


def test_baseline_selected_has_zero_savings_not_negative_zero() -> None:
    result = route_model(
        RiskLevel.MEDIUM,
        UseCase.CUSTOMER_CHATBOT,
        "Compare the options?",
    )
    assert result.selected_profile_id == result.baseline_profile_id == "standard"
    assert result.estimated_savings_usd == 0.0
    assert result.estimated_savings_percent == 0.0


def test_very_similar_candidates_follow_cost_constraint_not_registry_order() -> None:
    profiles = _profiles()
    standard = next(item for item in profiles if item.id == "standard")
    premium = next(item for item in profiles if item.id == "premium")
    standard.capability_score = 0.83
    premium.capability_score = 0.84
    standard.input_cost_per_1m_tokens = 0.20
    standard.output_cost_per_1m_tokens = 0.20
    premium.input_cost_per_1m_tokens = 0.21
    premium.output_cost_per_1m_tokens = 0.21
    result = route_model(
        RiskLevel.MEDIUM,
        UseCase.CUSTOMER_CHATBOT,
        "Compare choices?",
        profiles=list(reversed(profiles)),
    )
    assert result.selected_profile_id == "standard"


def test_disabled_economy_is_never_selected() -> None:
    profiles = _profiles()
    next(item for item in profiles if item.id == "economy").enabled = False
    result = route_model(
        RiskLevel.LOW,
        UseCase.CUSTOMER_CHATBOT,
        "Track order",
        profiles=profiles,
    )
    assert result.selected_profile_id == "standard"
    assert result.selected_tier != ModelTier.ECONOMY


def test_all_disabled_profiles_fail_explicitly() -> None:
    profiles = _profiles()
    for profile in profiles:
        profile.enabled = False
    with pytest.raises(RuntimeError, match="No enabled model profiles"):
        route_model(
            RiskLevel.LOW,
            UseCase.CUSTOMER_CHATBOT,
            "Track order",
            profiles=profiles,
        )


def test_exact_context_limit_is_allowed_and_one_token_over_is_rejected() -> None:
    profiles = _profiles()
    economy = next(item for item in profiles if item.id == "economy")
    standard = next(item for item in profiles if item.id == "standard")
    economy.capability_score = 0.90
    standard.capability_score = 0.91
    economy.context_window = 8192
    standard.context_window = 32768
    at_limit = route_model(
        RiskLevel.LOW,
        UseCase.CUSTOMER_CHATBOT,
        "context test",
        estimated_input_tokens=7680,
        estimated_output_tokens=512,
        profiles=profiles,
    )
    over_limit = route_model(
        RiskLevel.LOW,
        UseCase.CUSTOMER_CHATBOT,
        "context test",
        estimated_input_tokens=7681,
        estimated_output_tokens=512,
        profiles=profiles,
    )
    assert at_limit.selected_profile_id == "economy"
    assert over_limit.selected_profile_id == "standard"


def test_impossible_latency_and_context_preserve_capability_and_report_both() -> None:
    result = route_model(
        RiskLevel.HIGH,
        UseCase.FINANCE_TOOL,
        "Constrained regulated request",
        latency_budget_ms=100,
        estimated_input_tokens=140_000,
        estimated_output_tokens=1000,
    )
    assert result.selected_tier == ModelTier.PREMIUM
    assert result.capability_requirement_met
    assert result.context_window_sufficient is False
    assert {"context_window", "latency_budget"}.issubset(result.unmet_constraints)
    assert result.generation_approved is False
    assert result.routing_failure is True


def test_under_capable_economy_scores_worse_on_model_fit() -> None:
    profiles = _profiles()
    for profile in profiles:
        if profile.id != "economy":
            profile.enabled = False
    route = route_model(
        RiskLevel.HIGH,
        UseCase.FINANCE_TOOL,
        "Approve?",
        profiles=profiles,
    )
    efficiency = evaluate_efficiency(route)
    assert route.selected_tier == ModelTier.ECONOMY
    assert route.capability_requirement_met is False
    assert route.generation_approved is False
    assert efficiency.model_fit_score < 1.0
    assert efficiency.overall_efficiency_score < 0.5
    assert "capability_requirement" in route.unmet_constraints


def test_efficiency_uses_actual_latency_without_relabeling_estimates_as_actual_cost() -> None:
    route = route_model(
        RiskLevel.LOW,
        UseCase.CUSTOMER_CHATBOT,
        "Track order",
    )
    fast = evaluate_efficiency(route, actual_latency_ms=100)
    slow = evaluate_efficiency(route, actual_latency_ms=1400)
    assert fast.latency_score == 1.0
    assert slow.latency_score < fast.latency_score
    assert slow.latency_budget_breached is True
    assert slow.values_are_estimated is True
    assert slow.estimated_cost_usd == route.estimated_cost_usd


def test_negative_savings_are_explained_as_governance_tradeoff() -> None:
    route = route_model(
        RiskLevel.HIGH,
        UseCase.FINANCE_TOOL,
        "Approve?",
    )
    efficiency = evaluate_efficiency(route)
    assert efficiency.estimated_savings_usd < 0
    assert any("stronger model" in reason for reason in efficiency.explanation)


def test_invalid_latency_budget_is_rejected_instead_of_silently_replaced() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        route_model(
            RiskLevel.LOW,
            UseCase.CUSTOMER_CHATBOT,
            "Track order",
            latency_budget_ms=0,
        )


def test_pipeline_exposes_efficiency_without_extra_generation_call(monkeypatch) -> None:
    calls = 0

    async def clean_injection(prompt: str):
        return InjectionResult(detected=False)

    async def clean_pii(text: str, scan_target: str = "prompt"):
        return PIIResult(found=False, scan_target=scan_target)

    async def clean_bias(text: str):
        return BiasResult(detected=False)

    async def supported(response: str, use_case: UseCase):
        return GroundednessResult(
            verdict=GroundednessVerdict.SUPPORTED,
            score=1.0,
            total_claims_checked=1,
            grounded_claims_count=1,
            use_case_kb_used=use_case,
        )

    async def fake_llm(prompt: str, model_config, use_case: str):
        nonlocal calls
        calls += 1
        return "Your order is being processed.", 8, 6

    async def allow_policy(**kwargs):
        return PolicyDecision(
            approved=True,
            final_action=ActionType.ALLOW,
            reason="clean",
            policy_file="tests/policy",
            threshold_applied=0.2,
        )

    monkeypatch.setattr(pipeline, "injection_scan", clean_injection)
    monkeypatch.setattr(pipeline, "detect_pii", clean_pii)
    monkeypatch.setattr(pipeline, "detect_bias", clean_bias)
    monkeypatch.setattr(pipeline, "scan_toxic_content", None)
    monkeypatch.setattr(pipeline, "groundedness_check", supported)
    monkeypatch.setattr(pipeline, "_call_llm", fake_llm)
    monkeypatch.setattr(pipeline, "evaluate_policy", allow_policy)

    action, audit = asyncio.run(
        pipeline.run_pipeline(
            InterceptRequest(
                prompt="Where is my order?",
                use_case=UseCase.CUSTOMER_CHATBOT,
                tenant_id="tenant-phase3",
                user_id="user-phase3",
            )
        )
    )
    assert calls == 1
    assert audit.efficiency is not None
    assert audit.efficiency.selected_tier == ModelTier.ECONOMY
    assert audit.estimated_cost_usd == audit.efficiency.estimated_cost_usd
    assert action.evidence["efficiency"]["selected_tier"] == ModelTier.ECONOMY


def test_high_finance_with_only_economy_escalates_without_generation(monkeypatch) -> None:
    profiles = _profiles()
    for profile in profiles:
        profile.enabled = profile.id == "economy"

    def unsafe_route(risk, use_case, prompt, *, latency_budget_ms=None):
        return route_model(
            RiskLevel.HIGH,
            UseCase.FINANCE_TOOL,
            prompt,
            profiles=profiles,
        )

    llm = AsyncMock(return_value=("unsafe generated content", 99, 88))
    _patch_pipeline_for_routing(monkeypatch, llm, RiskLevel.HIGH)
    monkeypatch.setattr(pipeline, "route_model", unsafe_route)

    action, audit = asyncio.run(pipeline.run_pipeline(_request(UseCase.FINANCE_TOOL)))

    llm.assert_not_called()
    assert action.action == ActionType.ESCALATE
    assert action.final_response == pipeline.ROUTING_FAILURE_MESSAGE
    assert "unsafe generated content" not in action.final_response
    assert action.original_response == ""
    assert audit.llm_response == ""
    assert audit.tokens_input == audit.tokens_output == audit.tokens_total == 0
    assert audit.estimated_cost_usd == 0.0
    assert audit.model_used == "none"
    assert audit.action.evidence["routing_failure"] is True
    assert audit.action.evidence["candidate_approved_for_generation"] is False
    assert {
        "capability_requirement",
        "risk_policy",
        "use_case_support",
    }.issubset(audit.action.evidence["unmet_hard_constraints"])


def test_high_hr_with_under_capable_models_escalates_without_generation(monkeypatch) -> None:
    profiles = _profiles()
    next(profile for profile in profiles if profile.id == "premium").enabled = False

    def unsafe_route(risk, use_case, prompt, *, latency_budget_ms=None):
        return route_model(
            RiskLevel.HIGH,
            UseCase.HR_COPILOT,
            prompt,
            profiles=profiles,
        )

    llm = AsyncMock(return_value=("unapproved HR content", 10, 10))
    _patch_pipeline_for_routing(monkeypatch, llm, RiskLevel.HIGH)
    monkeypatch.setattr(pipeline, "route_model", unsafe_route)

    action, audit = asyncio.run(pipeline.run_pipeline(_request(UseCase.HR_COPILOT)))

    llm.assert_not_called()
    assert action.action == ActionType.ESCALATE
    assert audit.action.evidence["selected_tier"] == ModelTier.STANDARD
    assert {"risk_policy", "capability_requirement"}.issubset(
        audit.action.evidence["unmet_hard_constraints"]
    )


def test_context_too_large_for_every_model_escalates_without_generation(monkeypatch) -> None:
    def impossible_context_route(risk, use_case, prompt, *, latency_budget_ms=None):
        return route_model(
            RiskLevel.LOW,
            UseCase.CUSTOMER_CHATBOT,
            prompt,
            estimated_input_tokens=140_000,
            estimated_output_tokens=1_000,
        )

    llm = AsyncMock(return_value=("context overflow content", 1, 1))
    _patch_pipeline_for_routing(monkeypatch, llm, RiskLevel.LOW)
    monkeypatch.setattr(pipeline, "route_model", impossible_context_route)

    action, audit = asyncio.run(
        pipeline.run_pipeline(_request(UseCase.CUSTOMER_CHATBOT))
    )

    llm.assert_not_called()
    assert action.action == ActionType.ESCALATE
    assert audit.action.evidence["unmet_hard_constraints"] == ["context_window"]
    assert audit.action.evidence["estimated_total_tokens"] == 141_000
    assert audit.action.evidence["candidate_context_window"] == 131_072


def test_latency_only_breach_keeps_safe_premium_and_generates(monkeypatch) -> None:
    def slow_safe_route(risk, use_case, prompt, *, latency_budget_ms=None):
        return route_model(
            RiskLevel.HIGH,
            UseCase.FINANCE_TOOL,
            prompt,
            latency_budget_ms=100,
        )

    llm = AsyncMock(return_value=("approved premium response", 7, 5))
    _patch_pipeline_for_routing(monkeypatch, llm, RiskLevel.HIGH)
    monkeypatch.setattr(pipeline, "route_model", slow_safe_route)

    action, audit = asyncio.run(pipeline.run_pipeline(_request(UseCase.FINANCE_TOOL)))

    llm.assert_awaited_once()
    assert action.action == ActionType.ALLOW
    assert action.final_response == "approved premium response"
    assert audit.efficiency.selected_tier == ModelTier.PREMIUM
    assert audit.efficiency.latency_budget_breached is True
    assert audit.efficiency.generation_performed is True
    assert audit.tokens_total == 12


def test_all_hard_constraints_satisfied_preserves_normal_generation(monkeypatch) -> None:
    llm = AsyncMock(return_value=("normal governed response", 4, 3))
    _patch_pipeline_for_routing(monkeypatch, llm, RiskLevel.LOW)

    action, audit = asyncio.run(
        pipeline.run_pipeline(_request(UseCase.CUSTOMER_CHATBOT))
    )

    llm.assert_awaited_once()
    assert action.action == ActionType.ALLOW
    assert action.final_response == "normal governed response"
    assert audit.efficiency.selected_tier == ModelTier.ECONOMY
    assert audit.efficiency.generation_performed is True
    assert audit.action.evidence["efficiency"]["generation_performed"] is True
