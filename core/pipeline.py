"""
SentinelAI — Central Pipeline Orchestrator

The heart of SentinelAI. Every request flows through run_pipeline().
Orchestrates the 5-step governance pipeline:
  Step 1 — SCAN:           detect injection + PII in incoming prompt
  Step 2 — CLASSIFY:       assign risk level based on scan results
  Step 3 — ROUTE+GENERATE: pick the right LLM model, call it, get response
  Step 4 — EVALUATE:       run trust/responsibility and efficiency evaluation
  Step 5 — ACT+LOG:        take governed action, write to audit log

Engine ownership in the existing prototype:
  Responsibility: PII, bias, and deterministic policy-as-code
  Efficiency/persistence: model router and route-owned audit logger
  Self:   injection_detector, groundedness, risk_scorer, action_layer
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from api.schemas import (
    ActionResult,
    ActionType,
    AuditEntry,
    BiasResult,
    DetectorStatus,
    EfficiencyResult,
    GroundednessResult,
    GroundednessVerdict,
    InjectionResult,
    InterceptRequest,
    ModelConfig,
    PIIResult,
    PolicyDecision,
    RiskBreakdown,
    RiskLevel,
    RiskScore,
    UseCase,
)

logger = logging.getLogger("sentinelai")

ROUTING_FAILURE_MESSAGE = (
    "SentinelAI could not find an approved model that satisfies the required "
    "safety and capability constraints. This request requires review."
)


# ── Core engine imports with fail-safe availability fallbacks ─────────────────
try:
    from core.injection_detector import scan as injection_scan
    from core.injection_detector import scan_toxic_content
except ImportError:
    injection_scan = None
    scan_toxic_content = None
    logger.warning("Injection detector unavailable; fail-safe fallback active")

try:
    from engines.trust.groundedness import check as groundedness_check
except ImportError:
    groundedness_check = None
    logger.warning("Groundedness engine unavailable; fail-safe fallback active")

try:
    from engines.trust.groundedness import (
        retrieve_generation_evidence as retrieve_grounding_evidence,
    )
except ImportError:
    retrieve_grounding_evidence = None
    logger.warning("Pre-generation evidence retrieval unavailable")

try:
    from core.risk_scorer import compute as compute_risk
except ImportError:
    compute_risk = None
    logger.warning("Risk scorer unavailable; fail-safe fallback active")

try:
    from core.action_layer import execute as execute_action
except ImportError:
    execute_action = None
    logger.warning("Action layer unavailable; fail-safe fallback active")

try:
    from core.action_layer import BLOCK_MESSAGES, DEFAULT_BLOCK_MESSAGE
except ImportError:
    BLOCK_MESSAGES = {}
    DEFAULT_BLOCK_MESSAGE = "I'm unable to process this request."
    logger.warning("action_layer constants not found — using defaults")

# ── Responsibility engine imports ─────────────────────────────────────────────
try:
    from engines.responsibility.pii_detector import detect_pii
except ImportError:
    detect_pii = None
    logger.warning("PII detector unavailable; fail-safe fallback active")

try:
    from engines.responsibility.bias_detector import detect_bias
except ImportError:
    detect_bias = None
    logger.warning("Bias detector unavailable; fail-safe fallback active")

try:
    from policy.engine import evaluate_policy, fallback_policy_decision
except ImportError:
    evaluate_policy = None
    fallback_policy_decision = None
    logger.warning("Policy engine unavailable; fail-safe fallback active")

# ── Efficiency engine import ──────────────────────────────────────────────────
try:
    from engines.efficiency.model_router import (
        evaluate_efficiency,
        hard_routing_failures,
        has_hard_routing_failure,
        route_model,
        routing_from_model_config,
    )
except ImportError:
    route_model = None
    evaluate_efficiency = None
    hard_routing_failures = None
    has_hard_routing_failure = None
    routing_from_model_config = None
    logger.warning("Model router unavailable; deterministic fallback active")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Central LiteLLM call used for initial generation and a bounded repair attempt
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MAX_GENERATION_EVIDENCE_SOURCES = 3
MAX_GENERATION_EVIDENCE_CHARS_PER_SOURCE = 1800


def _build_grounded_generation_prompt(
    user_prompt: str,
    evidence: list[dict],
) -> str:
    """Add bounded, source-labelled local evidence to the generation request."""
    if not evidence:
        return user_prompt

    source_blocks: list[str] = []
    for index, source in enumerate(
        evidence[:MAX_GENERATION_EVIDENCE_SOURCES], start=1
    ):
        content = str(source.get("content", "")).strip()
        if not content:
            continue
        source_blocks.append(
            "\n".join(
                (
                    f"[APPROVED SOURCE {index}]",
                    f"ID: {str(source.get('doc_id', 'unknown'))}",
                    f"Title: {str(source.get('title', 'Untitled policy'))}",
                    content[:MAX_GENERATION_EVIDENCE_CHARS_PER_SOURCE],
                )
            )
        )
    if not source_blocks:
        return user_prompt

    return (
        "Answer the user question using only the approved local evidence below. "
        "Return only the minimum complete policy sentences copied from the evidence "
        "that answer the question. Do not add an introduction, conclusion, company "
        "name, policy title, contact details, unsupported recommendations, assumptions, "
        "or outside knowledge. If the evidence does not answer the question, say that "
        "the policy cannot be verified from the available evidence.\n\n"
        f"USER QUESTION:\n{user_prompt}\n\n"
        "APPROVED LOCAL EVIDENCE:\n"
        + "\n\n".join(source_blocks)
    )


async def _call_llm(prompt: str, model_config, use_case: str = "hr_copilot") -> tuple[str, int, int]:
    """
    Calls the LLM via Groq using LiteLLM.
    Returns (response_text, tokens_input, tokens_output).

    Model selected by model_router based on risk level + use case.
    Default: groq/qwen/qwen3.8-27b (2M tokens/day free tier — no limit risk)

    Args:
        prompt:       User prompt to send to LLM
        model_config: ModelConfig object or dict with model, max_tokens, temperature

    Returns:
        tuple of (response_text, tokens_input, tokens_output)
    """
    import litellm
    import os

    # Extract config — handle both ModelConfig object and plain dict
    if isinstance(model_config, dict):
        model       = model_config.get("model", "groq/qwen/qwen3.8-27b")
        max_tokens  = model_config.get("max_tokens", 500)
        temperature = model_config.get("temperature", 0.3)
    else:
        model       = getattr(model_config, "model", "groq/qwen/qwen3.8-27b")
        max_tokens  = getattr(model_config, "max_tokens", 500)
        temperature = getattr(model_config, "temperature", 0.3)

    # Ensure Groq provider prefix
    if not model.startswith("groq/"):
        model = f"groq/{model}"

    logger.info(
        f"Calling LLM | model={model} | "
        f"max_tokens={max_tokens} | temperature={temperature}"
    )

    try:
        # Use-case-specific system prompts with hard-coded Acme Corp facts.
        # Each prompt tells the LLM exactly what role it plays and what data it has.
        SYSTEM_PROMPTS = {
            "customer_chatbot": (
                "You are Acme Corp's customer support assistant. "
                "You have full knowledge of Acme Corp's policies: "
                "30-day return window, free shipping on orders over $50, "
                "express shipping $12.99 (2-3 days), standard shipping 5-7 days, "
                "1-year warranty on electronics, 90-day warranty on accessories, "
                "support hours Monday-Friday 9am-6pm EST. "
                "Answer customer questions directly and specifically using these facts. "
                "Be concise. Do not say you lack access to information."
            ),
            "hr_copilot": (
                "You are Acme Corp's internal HR assistant. "
                "You have full knowledge of Acme Corp HR policies: "
                "employees get 10 paid sick days per year, "
                "15 days annual leave per year (20 days after 5 years), "
                "remote work up to 3 days per week, "
                "performance reviews in June and December, "
                "12 weeks paid parental leave, "
                "expense reimbursement up to $500 per quarter without approval, "
                "health insurance with 80% premium covered, 401k match up to 4%. "
                "Answer employee questions directly using these specific Acme Corp facts. "
                "Always state the exact number or policy. Do not hedge or say you lack access."
            ),
            "finance_tool": (
                "You are Acme Corp's internal finance assistant. "
                "You have access to Acme Corp financial data: "
                "Q1 2026 revenue $4.2M (12% YoY growth), "
                "Q2 2026 revenue $4.8M (14% YoY growth), "
                "North America 68% of revenue, Europe 22%, APAC 10%, "
                "gross margin 62%, EBITDA margin 24%, "
                "CAC $142, monthly active users 84000, R&D spend 18% of revenue. "
                "Answer finance questions directly using these specific Acme Corp metrics. "
                "Always cite the exact figures. Do not hedge or say you lack access."
            ),
        }

        system_prompt = SYSTEM_PROMPTS.get(use_case, SYSTEM_PROMPTS["hr_copilot"])
        if isinstance(model_config, dict):
            system_prompt = model_config.get("_system_prompt_override", system_prompt)

        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=os.getenv("GROQ_API_KEY"),
        )

        response_text = response.choices[0].message.content
        tokens_input  = response.usage.prompt_tokens
        tokens_output = response.usage.completion_tokens

        logger.info(
            f"LLM call complete | model={model} | "
            f"tokens_in={tokens_input} | tokens_out={tokens_output}"
        )

        return response_text, tokens_input, tokens_output

    except Exception as e:
        logger.error("LLM call failed | model=%s | error_type=%s", model, type(e).__name__)
        # Safe fallback — never let LLM failure crash the pipeline
        fallback = (
            "I'm unable to process this request at the moment. "
            "Please try again shortly."
        )
        return fallback, 0, 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Mock returns for engine functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _mock_injection_result() -> InjectionResult:
    """Return an explicit unavailable result when the detector cannot load."""
    return InjectionResult(
        detected=False,
        status=DetectorStatus.UNAVAILABLE,
        confidence=0.0,
        method="none",
    )


def _mock_pii_result(scan_target: str = "prompt") -> PIIResult:
    """Return an explicit unavailable result when the detector cannot load."""
    return PIIResult(
        found=False,
        status=DetectorStatus.UNAVAILABLE,
        risk_score=0.0,
        scan_target=scan_target,
    )


def _mock_bias_result() -> BiasResult:
    """Return an explicit unavailable result when the detector cannot load."""
    return BiasResult(
        detected=False,
        status=DetectorStatus.UNAVAILABLE,
        score=0.0,
        confidence=0.0,
        detection_method="unavailable",
    )


def _mock_groundedness_result(use_case: UseCase) -> GroundednessResult:
    """Return an explicit unavailable result, never a verified score."""
    return GroundednessResult(
        status=DetectorStatus.UNAVAILABLE,
        verdict=GroundednessVerdict.UNAVAILABLE,
        score=0.0,
        total_claims_checked=0,
        grounded_claims_count=0,
        use_case_kb_used=use_case,
    )


def _apply_groundedness_policy_guard(
    decision: PolicyDecision,
    groundedness: GroundednessResult,
    use_case: UseCase,
) -> PolicyDecision:
    """Apply only the minimum evidence guard; stronger configured actions win."""
    action = decision.final_action
    if action in {ActionType.BLOCK, ActionType.ESCALATE, ActionType.REDACT}:
        return decision

    repairable = any(
        evaluation.verdict == GroundednessVerdict.CONTRADICTED
        and bool(evaluation.source_excerpt)
        for evaluation in groundedness.claim_evaluations
    )
    if groundedness.verdict == GroundednessVerdict.CONTRADICTED:
        guarded_action = ActionType.REPAIR if repairable else ActionType.ESCALATE
        reason = (
            "Groundedness contradiction requires one evidence-constrained repair."
            if repairable
            else "Groundedness contradiction lacks repair evidence and requires review."
        )
    elif groundedness.verdict == GroundednessVerdict.INSUFFICIENT_EVIDENCE:
        guarded_action = ActionType.ESCALATE
        reason = (
            "Local evidence is insufficient; the response is held for review"
            + (
                " in this regulated use case."
                if use_case in {UseCase.HR_COPILOT, UseCase.FINANCE_TOOL}
                else " because no safe-uncertainty policy is configured."
            )
        )
    else:
        return decision

    return PolicyDecision(
        approved=False,
        final_action=guarded_action,
        reason=reason,
        policy_file="policy/groundedness_guard",
        threshold_applied=decision.threshold_applied,
    )


def _mock_model_config() -> dict:
    """Compatibility fallback used only when the efficiency router cannot load."""
    return {
        "model": "groq/openai/gpt-oss-120b",
        "max_tokens": 200,
        "temperature": 0.3,
        "reason": "Fallback model configuration — efficiency router unavailable",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Pipeline Function
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def run_pipeline(
    request: InterceptRequest,
) -> tuple[ActionResult, AuditEntry]:
    """
    Central pipeline orchestrator. Runs every incoming request through
    the 5-step SentinelAI governance pipeline.

    Args:
        request: InterceptRequest containing prompt, use_case, tenant_id, user_id

    Returns:
        tuple of (ActionResult, AuditEntry)
        - ActionResult: the governed decision + final response to return to user
        - AuditEntry: complete record of this pipeline run for audit logging

    Flow:
        Step 1 — SCAN:           injection detection + PII scan on prompt
        Step 2 — CLASSIFY:       assign LOW/MEDIUM/HIGH risk level
        Step 3 — ROUTE+GENERATE: model selection + LLM call
        Step 4 — EVALUATE:       parallel trust/responsibility/efficiency checks
        Step 5 — ACT+LOG:        governed action + audit trail
    """
    pipeline_start = time.time()
    request_id = str(uuid.uuid4())
    use_case_str = request.use_case if isinstance(request.use_case, str) else request.use_case.value
    step_latencies: dict[str, int] = {}

    logger.info(
        f"Pipeline started | request_id={request_id} | "
        f"use_case={request.use_case} | tenant={request.tenant_id}"
    )

    # ──────────────────────────────────────────────────────────────────────
    # STEP 1 — SCAN
    # Scan the incoming prompt BEFORE it reaches the LLM.
    # Two checks run here: injection detection + PII in prompt.
    # If critical injection detected → immediately BLOCK, skip all steps.
    # ──────────────────────────────────────────────────────────────────────
    step_start = time.time()
    logger.info(f"[{request_id}] Step 1: SCAN starting...")

    # Injection detection
    # Run the configured injection engine, or retain explicit unavailable state.
    if injection_scan is not None:
        try:
            injection_result = await injection_scan(request.prompt)
        except Exception as exc:
            logger.error(
                "[%s] injection detector unavailable: %s",
                request_id,
                type(exc).__name__,
            )
            injection_result = _mock_injection_result()
    else:
        injection_result = _mock_injection_result()
        logger.debug(f"[{request_id}] injection_scan unavailable")

    # Early exit: critical injection → immediate BLOCK
    if injection_result.detected and injection_result.confidence >= 0.90:
        logger.warning(
            f"[{request_id}] CRITICAL INJECTION DETECTED — "
            f"confidence={injection_result.confidence:.2f} — immediate BLOCK"
        )
        # Build immediate block response without going through remaining steps
        block_result = ActionResult(
            action=ActionType.BLOCK,
            final_response=(
                "I'm unable to process this request. "
                "Please contact support if you believe this is an error."
            ),
            original_response="",
            explanation=(
                f"Prompt injection detected with confidence "
                f"{injection_result.confidence:.2f}"
            ),
            evidence={"injection": injection_result.model_dump()},
            escalation_required=False,
        )
        # Build minimal audit entry for this blocked request
        latency_ms = max(1, int((time.time() - pipeline_start) * 1000))
        audit_entry = _build_audit_entry(
            request_id=request_id,
            request=request,
            llm_response="[BLOCKED — injection detected]",
            action_result=block_result,
            injection_result=injection_result,
            pii_prompt_result=_mock_pii_result("prompt"),
            pii_response_result=_mock_pii_result("response"),
            groundedness_result=_mock_groundedness_result(request.use_case),
            bias_result=_mock_bias_result(),
            risk_score=RiskScore(
                overall=0.95,
                level=RiskLevel.HIGH,
                breakdown=RiskBreakdown(
                    injection_score=injection_result.confidence,
                    pii_prompt_score=0.0,
                    pii_response_score=0.0,
                    groundedness_risk=0.0,
                    bias_score=0.0,
                    dominant_signal="injection",
                ),
                use_case=request.use_case,
            ),
            policy_decision=PolicyDecision(
                approved=False,
                final_action=ActionType.BLOCK,
                reason="Injection detected — immediate block",
                policy_file="injection_guard",
                threshold_applied=0.90,
            ),
            model_used="none",
            tokens_input=0,
            tokens_output=0,
            latency_ms=latency_ms,
            step_latencies={"scan": latency_ms},
        )
        return block_result, audit_entry

    # PII scan on prompt.
    if detect_pii is not None:
        pii_prompt_result = await detect_pii(request.prompt)
    else:
        pii_prompt_result = _mock_pii_result("prompt")
        logger.debug(f"[{request_id}] detect_pii (prompt) unavailable")

    # Prompt safety check — detect harmful/toxic prompts
    # Catches sexual harassment, violence, illegal instructions etc.
    # Runs on PROMPT (not response) — different from bias_detector in Step 4
    if detect_bias is not None:
        prompt_safety = await detect_bias(request.prompt)
        if prompt_safety.detected and prompt_safety.score > 0.70:
            logger.warning(
                f"[{request_id}] HARMFUL PROMPT DETECTED — "
                f"score={prompt_safety.score:.3f} — immediate BLOCK"
            )
            block_result = ActionResult(
                action=ActionType.BLOCK,
                final_response=BLOCK_MESSAGES.get(
                    str(request.use_case),
                    DEFAULT_BLOCK_MESSAGE,
                ),
                original_response="",
                explanation=f"Harmful prompt detected with score {prompt_safety.score:.3f}",
                evidence={"prompt_safety": prompt_safety.score},
                escalation_required=True,
            )
            latency_ms = max(1, int((time.time() - pipeline_start) * 1000))
            audit_entry = _build_audit_entry(
                request_id=request_id,
                request=request,
                llm_response="[BLOCKED — harmful prompt]",
                action_result=block_result,
                injection_result=injection_result,
                pii_prompt_result=pii_prompt_result,
                pii_response_result=_mock_pii_result("response"),
                groundedness_result=_mock_groundedness_result(request.use_case),
                bias_result=prompt_safety,
                risk_score=RiskScore(
                    overall=0.95,
                    level=RiskLevel.HIGH,
                    breakdown=RiskBreakdown(
                        injection_score=0.0,
                        pii_prompt_score=0.0,
                        pii_response_score=0.0,
                        groundedness_risk=0.0,
                        bias_score=prompt_safety.score,
                        dominant_signal="bias",
                    ),
                    use_case=request.use_case,
                ),
                policy_decision=PolicyDecision(
                    approved=False,
                    final_action=ActionType.BLOCK,
                    reason="Harmful prompt detected",
                    policy_file="prompt_safety_guard",
                    threshold_applied=0.70,
                ),
                model_used="none",
                tokens_input=0,
                tokens_output=0,
                latency_ms=latency_ms,
                step_latencies={"scan": latency_ms},
            )
            return block_result, audit_entry

    # Semantic toxicity check — catches toxic content not covered by bias patterns
    # Runs AFTER injection check, BEFORE LLM call
    # Uses embedding similarity against toxic concept seeds in Qdrant
    if scan_toxic_content is not None:
        is_toxic, toxic_score, toxic_concept = await scan_toxic_content(request.prompt)
        if is_toxic and toxic_score > 0.72:
            logger.warning(
                f"[{request_id}] SEMANTIC TOXICITY DETECTED — "
                f"concept={toxic_concept} | "
                f"similarity={toxic_score:.3f} — immediate BLOCK"
            )
            toxic_block_result = ActionResult(
                action=ActionType.BLOCK,
                final_response=BLOCK_MESSAGES.get(
                    str(request.use_case),
                    DEFAULT_BLOCK_MESSAGE
                ),
                original_response="",
                explanation=f"Toxic content detected — concept: {toxic_concept} (semantic similarity: {toxic_score:.3f})",
                evidence={
                    "toxic_concept": toxic_concept,
                    "semantic_similarity": toxic_score,
                    "detection_method": "semantic_embedding",
                },
                escalation_required=True,
            )
            latency_ms = max(1, int((time.time() - pipeline_start) * 1000))
            audit_entry = _build_audit_entry(
                request_id=request_id,
                request=request,
                llm_response="[BLOCKED — toxic content detected]",
                action_result=toxic_block_result,
                injection_result=injection_result,
                pii_prompt_result=pii_prompt_result,
                pii_response_result=_mock_pii_result("response"),
                groundedness_result=_mock_groundedness_result(request.use_case),
                bias_result=BiasResult(
                    detected=True,
                    score=toxic_score,
                    confidence=toxic_score,
                    detection_method="semantic_embedding",
                    bias_types=[],
                    flagged_segments=[request.prompt[:100]],
                ),
                risk_score=RiskScore(
                    overall=0.95,
                    level=RiskLevel.HIGH,
                    breakdown=RiskBreakdown(
                        injection_score=0.0,
                        pii_prompt_score=0.0,
                        pii_response_score=0.0,
                        groundedness_risk=0.0,
                        bias_score=toxic_score,
                        dominant_signal="bias",
                    ),
                    use_case=request.use_case,
                ),
                policy_decision=PolicyDecision(
                    approved=False,
                    final_action=ActionType.BLOCK,
                    reason=f"Semantic toxicity detected — concept: {toxic_concept}",
                    policy_file="semantic_toxicity_guard",
                    threshold_applied=0.72,
                ),
                model_used="none",
                tokens_input=0,
                tokens_output=0,
                latency_ms=latency_ms,
                step_latencies={"scan": latency_ms},
            )
            return toxic_block_result, audit_entry

    step_latencies["scan"] = int((time.time() - step_start) * 1000)
    logger.info(
        f"[{request_id}] Step 1 complete | "
        f"injection={injection_result.detected} | "
        f"pii_in_prompt={pii_prompt_result.found} | "
        f"latency={step_latencies['scan']}ms"
    )

    # ──────────────────────────────────────────────────────────────────────
    # STEP 2 — CLASSIFY
    # Assign a risk level based on scan results and use case.
    # This controls how deeply we evaluate in Step 4.
    # LOW  → skip deep checks, fast path to LLM
    # MEDIUM → run trust + responsibility checks
    # HIGH → run all checks including bias
    # ──────────────────────────────────────────────────────────────────────
    step_start = time.time()
    logger.info(f"[{request_id}] Step 2: CLASSIFY starting...")

    # Deterministic preliminary classification feeds capability-first routing.
    # Real logic considers:
    #   - injection_result.confidence
    #   - pii_prompt_result.risk_score
    #   - request.use_case (customer_chatbot = stricter = higher initial risk)
    #   - request.prompt length and complexity
    preliminary_risk_level = _classify_risk(
        injection_result=injection_result,
        pii_prompt=pii_prompt_result,
        use_case=request.use_case,
    )

    step_latencies["classify"] = int((time.time() - step_start) * 1000)
    logger.info(
        f"[{request_id}] Step 2 complete | "
        f"risk_level={preliminary_risk_level} | "
        f"latency={step_latencies['classify']}ms"
    )

    # ──────────────────────────────────────────────────────────────────────
    # STEP 3 — ROUTE + GENERATE
    # Pick the right LLM model based on risk level + use case.
    # Then call the LLM and get the raw response.
    # ──────────────────────────────────────────────────────────────────────
    step_start = time.time()
    logger.info(f"[{request_id}] Step 3: ROUTE + GENERATE starting...")

    requested_latency_budget = None
    if request.metadata and request.metadata.get("latency_budget_ms") is not None:
        requested_latency_budget = int(request.metadata["latency_budget_ms"])

    # Deterministic capability-first routing. This makes no additional LLM call.
    if route_model is not None:
        router_parameters = inspect.signature(route_model).parameters
        if "latency_budget_ms" in router_parameters:
            model_config = route_model(
                preliminary_risk_level,
                request.use_case,
                request.prompt,
                latency_budget_ms=requested_latency_budget,
            )
        else:
            # Preserve compatibility with older two-argument router plugins.
            model_config = route_model(preliminary_risk_level, request.use_case)
    else:
        model_config = _mock_model_config()
        logger.debug(f"[{request_id}] route_model unavailable; using fallback")

    routing_result = (
        routing_from_model_config(
            model_config,
            preliminary_risk_level,
            request.use_case,
            request.prompt,
        )
        if routing_from_model_config is not None
        else None
    )

    # A fallback candidate is observable but is not approved when any hard
    # routing constraint failed. Fail closed before any generation provider call.
    if (
        routing_result is not None
        and has_hard_routing_failure is not None
        and has_hard_routing_failure(routing_result)
    ):
        hard_failures = hard_routing_failures(routing_result)
        hard_failure_values = [
            str(getattr(constraint, "value", constraint))
            for constraint in hard_failures
        ]
        all_unmet_values = [
            str(getattr(constraint, "value", constraint))
            for constraint in routing_result.unmet_constraints
        ]
        efficiency_result = (
            evaluate_efficiency(routing_result, generation_performed=False)
            if evaluate_efficiency is not None
            else None
        )
        routing_evidence = {
            "routing_failure": True,
            "candidate_approved_for_generation": False,
            "selected_model": routing_result.selected_model,
            "selected_profile_id": routing_result.selected_profile_id,
            "selected_tier": routing_result.selected_tier,
            "unmet_hard_constraints": hard_failure_values,
            "unmet_constraints": all_unmet_values,
            "routing_reason": routing_result.routing_reason,
            "use_case": use_case_str,
            "risk_level": preliminary_risk_level,
            "capability_required": routing_result.capability_required,
            "capability_available": routing_result.capability_selected,
            "estimated_input_tokens": routing_result.estimated_input_tokens,
            "estimated_output_tokens": routing_result.estimated_output_tokens,
            "estimated_total_tokens": (
                routing_result.estimated_input_tokens
                + routing_result.estimated_output_tokens
            ),
            "candidate_context_window": routing_result.context_window_selected,
            "estimated_generation_cost_usd": 0.0,
        }
        if efficiency_result is not None:
            routing_evidence["efficiency"] = efficiency_result.model_dump()

        action_result = ActionResult(
            action=ActionType.ESCALATE,
            final_response=ROUTING_FAILURE_MESSAGE,
            original_response="",
            explanation=(
                "The router identified a best-available candidate, but it was not "
                "approved for generation because hard constraints were unmet."
            ),
            evidence=routing_evidence,
            escalation_required=True,
        )
        risk_score = _mock_risk_score(request.use_case, preliminary_risk_level)
        policy_decision = PolicyDecision(
            approved=False,
            final_action=ActionType.ESCALATE,
            reason="Hard routing constraints failed before generation.",
            policy_file="policy/routing_preflight",
            threshold_applied=0.0,
            policy_rule_ids=["routing_hard_constraint_failure"],
        )
        step_latencies["route"] = int((time.time() - step_start) * 1000)
        step_latencies["generate"] = 0
        step_latencies["evaluate"] = 0
        step_latencies["act"] = 0
        total_latency_ms = max(1, int((time.time() - pipeline_start) * 1000))
        step_latencies["total"] = total_latency_ms
        audit_entry = _build_audit_entry(
            request_id=request_id,
            request=request,
            llm_response="",
            action_result=action_result,
            injection_result=injection_result,
            pii_prompt_result=pii_prompt_result,
            pii_response_result=_mock_pii_result("response"),
            groundedness_result=_mock_groundedness_result(request.use_case),
            bias_result=_mock_bias_result(),
            risk_score=risk_score,
            policy_decision=policy_decision,
            model_used="none",
            tokens_input=0,
            tokens_output=0,
            latency_ms=total_latency_ms,
            step_latencies=step_latencies,
            efficiency_result=efficiency_result,
        )
        logger.warning(
            "[%s] Generation blocked by hard routing constraints | candidate=%s | failures=%s",
            request_id,
            routing_result.selected_model,
            hard_failure_values,
        )
        return action_result, audit_entry

    # Retrieve approved use-case evidence before the first generation. This is
    # bounded and does not weaken the authoritative post-generation verifier.
    generation_prompt = request.prompt
    retrieved_evidence: list[dict] = []
    retrieval_started = time.time()
    if retrieve_grounding_evidence is not None:
        try:
            retrieved_evidence = await retrieve_grounding_evidence(
                request.prompt,
                request.use_case,
                top_k=MAX_GENERATION_EVIDENCE_SOURCES,
            )
            generation_prompt = _build_grounded_generation_prompt(
                request.prompt,
                retrieved_evidence,
            )
        except Exception as exc:
            logger.warning(
                "[%s] Pre-generation evidence retrieval unavailable: %s",
                request_id,
                type(exc).__name__,
            )
    step_latencies["retrieve"] = int((time.time() - retrieval_started) * 1000)

    # LLM call
    llm_response, tokens_input, tokens_output = await _call_llm(
        prompt=generation_prompt,
        model_config=model_config,
        use_case=use_case_str,
    )
    model_used = (
        model_config["model"]
        if isinstance(model_config, dict)
        else model_config.model
    )

    step_latencies["generate"] = int((time.time() - step_start) * 1000)
    logger.info(
        f"[{request_id}] Step 3 complete | "
        f"model={model_used} | "
        f"tokens_in={tokens_input} | tokens_out={tokens_output} | "
        f"evidence_sources={len(retrieved_evidence)} | "
        f"latency={step_latencies['generate']}ms"
    )

    # ──────────────────────────────────────────────────────────────────────
    # STEP 4 — EVALUATE
    # External trust/responsibility engines run concurrently. Efficiency scoring
    # is deterministic and local, so it adds no model call.
    #
    # Engine A: groundedness.py    → is the response factually grounded?
    # Engine B: pii_detector.py    → does the response contain PII?
    # Engine C: bias_detector.py   → does the response contain bias?
    #
    # ──────────────────────────────────────────────────────────────────────
    step_start = time.time()
    logger.info(f"[{request_id}] Step 4: EVALUATE starting (parallel engines)...")

    # Run engines — use real if available, mock if not
    async def _run_groundedness():
        """Run groundedness check or return an explicit unavailable result."""
        if groundedness_check is not None:
            try:
                return await groundedness_check(llm_response, request.use_case)
            except Exception as exc:
                logger.error(
                    "[%s] groundedness detector unavailable: %s",
                    request_id,
                    type(exc).__name__,
                )
        logger.debug(f"[{request_id}] groundedness_check unavailable")
        return _mock_groundedness_result(request.use_case)

    async def _run_pii_response():
        """Run PII scan on LLM response or return mock."""
        if detect_pii is not None:
            result = await detect_pii(llm_response, scan_target="response")
            result.scan_target = "response"
            return result
        logger.debug(
            f"[{request_id}] detect_pii (response) unavailable"
        )
        return _mock_pii_result("response")

    async def _run_bias():
        """
        Run bias detection on BOTH prompt and LLM response.
        Combines scores — takes the higher of the two.
        This catches:
          - Biased LLM outputs (response scanning)
          - Biased user requests that the LLM might partially fulfill (prompt scanning)
        """
        if detect_bias is None:
            logger.debug(f"[{request_id}] detect_bias unavailable")
            return _mock_bias_result()

        # Run prompt and response bias scans in parallel
        prompt_bias, response_bias = await asyncio.gather(
            detect_bias(request.prompt),
            detect_bias(llm_response),
        )

        any_unavailable = any(
            result.status == DetectorStatus.UNAVAILABLE
            for result in (prompt_bias, response_bias)
        )

        # Return whichever has higher risk score
        if prompt_bias.score >= response_bias.score:
            logger.debug(
                f"[{request_id}] Bias: prompt score {prompt_bias.score:.3f} "
                f"higher than response score {response_bias.score:.3f}"
            )
            selected = prompt_bias
        else:
            logger.debug(
                f"[{request_id}] Bias: response score {response_bias.score:.3f} "
                f"higher than prompt score {prompt_bias.score:.3f}"
            )
            selected = response_bias
        if any_unavailable:
            selected.status = DetectorStatus.UNAVAILABLE
        return selected

    # External response evaluators run simultaneously, not sequentially.
    groundedness_result, pii_response_result, bias_result = await asyncio.gather(
        _run_groundedness(),
        _run_pii_response(),
        _run_bias(),
    )

    efficiency_result = (
        evaluate_efficiency(
            routing_result,
            actual_latency_ms=step_latencies.get("generate", 0),
        )
        if evaluate_efficiency is not None and routing_result is not None
        else None
    )

    step_latencies["evaluate"] = int((time.time() - step_start) * 1000)
    logger.info(
        f"[{request_id}] Step 4 complete | "
        f"groundedness={groundedness_result.verdict} "
        f"({groundedness_result.score:.2f}) | "
        f"pii_in_response={pii_response_result.found} | "
        f"bias={bias_result.detected} | "
        f"latency={step_latencies['evaluate']}ms"
    )

    # ──────────────────────────────────────────────────────────────────────
    # STEP 5 — ACT + LOG
    # Combine all engine results into a risk score.
    # Get a decision from the deterministic YAML policy-as-code engine.
    # Execute the governed action.
    # Log everything to audit trail (non-blocking).
    # ──────────────────────────────────────────────────────────────────────
    step_start = time.time()
    logger.info(f"[{request_id}] Step 5: ACT + LOG starting...")

    # Risk scoring
    # Combine detector results into the configured use-case risk score.
    if compute_risk is not None:
        risk_score = compute_risk(
            injection=injection_result,
            pii_prompt=pii_prompt_result,
            groundedness=groundedness_result,
            pii_response=pii_response_result,
            bias=bias_result,
            use_case=request.use_case,
        )
    else:
        risk_score = _mock_risk_score(request.use_case, preliminary_risk_level)
        logger.debug(f"[{request_id}] compute_risk unavailable; using fail-safe score")

    unavailable_detectors = [
        name
        for name, result in (
            ("injection", injection_result),
            ("pii_prompt", pii_prompt_result),
            ("pii_response", pii_response_result),
            ("groundedness", groundedness_result),
            ("bias", bias_result),
        )
        if result.status == DetectorStatus.UNAVAILABLE
    ]

    # Policy evaluation with a deterministic fail-safe boundary.
    if evaluate_policy is not None:
        try:
            policy_decision = await evaluate_policy(
                use_case=request.use_case,
                risk_score=risk_score,
                pii_detected=pii_response_result.found,
                bias_detected=bias_result.detected,
                secrets_detected=False,
                injection_detected=injection_result.detected,
                unavailable_detectors=unavailable_detectors,
            )
        except Exception as exc:
            logger.error(
                "[%s] policy evaluator unavailable: %s",
                request_id,
                type(exc).__name__,
            )
            policy_decision = fallback_policy_decision(
                request.use_case,
                risk_score,
                pii_detected=pii_response_result.found,
                bias_detected=bias_result.detected,
                injection_detected=injection_result.detected,
                unavailable_detectors=unavailable_detectors,
            )
    else:
        policy_decision = fallback_policy_decision(
            request.use_case,
            risk_score,
            pii_detected=pii_response_result.found,
            bias_detected=bias_result.detected,
            injection_detected=injection_result.detected,
            unavailable_detectors=unavailable_detectors,
        )
        logger.info(
            f"[{request_id}] Inline policy fallback | "
            f"action={policy_decision.final_action} | reason={policy_decision.reason}"
        )

    policy_decision = _apply_groundedness_policy_guard(
        policy_decision,
        groundedness_result,
        request.use_case,
    )

    async def _repair_once(repair_prompt: str) -> tuple[str, GroundednessResult]:
        """Make exactly one bounded generation and one verification pass."""
        nonlocal tokens_input, tokens_output
        if isinstance(model_config, dict):
            repair_config = {
                **model_config,
                "temperature": min(float(model_config.get("temperature", 0.2)), 0.2),
                "max_tokens": min(int(model_config.get("max_tokens", 400)), 400),
                "_system_prompt_override": (
                    "You correct answers using only evidence supplied in the user "
                    "message. Never use outside facts. Return only the answer."
                ),
            }
        else:
            repair_config = {
                **model_config.model_dump(),
                "temperature": min(float(model_config.temperature), 0.2),
                "max_tokens": min(int(model_config.max_tokens), 400),
                "_system_prompt_override": (
                    "You correct answers using only evidence supplied in the user "
                    "message. Never use outside facts. Return only the answer."
                ),
            }
        repaired, repair_tokens_in, repair_tokens_out = await _call_llm(
            prompt=repair_prompt,
            model_config=repair_config,
            use_case=use_case_str,
        )
        tokens_input += repair_tokens_in
        tokens_output += repair_tokens_out
        if groundedness_check is None:
            return repaired, _mock_groundedness_result(request.use_case)
        try:
            recheck = await groundedness_check(repaired, request.use_case)
        except Exception as exc:
            logger.error(
                "[%s] repair re-verification unavailable: %s",
                request_id,
                type(exc).__name__,
            )
            recheck = _mock_groundedness_result(request.use_case)
        return repaired, recheck

    # Action execution
    # Execute the governed action selected by policy.
    if execute_action is not None:
        action_result = await execute_action(
            policy_decision=policy_decision,
            risk_score=risk_score,
            llm_response=llm_response,
            pii_in_response=pii_response_result,
            use_case=request.use_case,
            original_prompt=request.prompt,
            groundedness_result=groundedness_result,
            repair_callback=_repair_once,
        )
    else:
        logger.error(
            "[%s] action layer unavailable; defaulting to BLOCK",
            request_id,
        )
        action_result = ActionResult(
            action=ActionType.BLOCK,
            final_response=DEFAULT_BLOCK_MESSAGE,
            original_response=llm_response,
            explanation="Action layer unavailable; response blocked for safety.",
            evidence={
                "risk_score": risk_score.overall,
                "risk_level": risk_score.level,
                "policy_reason": policy_decision.reason,
                "fallback_rule": "action_layer_unavailable_block",
            },
        )

    if efficiency_result is not None:
        efficiency_result.retry_count = action_result.repair_attempts
        action_result.evidence["efficiency"] = efficiency_result.model_dump()

    # Total pipeline latency
    total_latency_ms = max(1, int((time.time() - pipeline_start) * 1000))
    step_latencies["act"] = int((time.time() - step_start) * 1000)
    step_latencies["total"] = total_latency_ms

    # Build audit entry
    audit_entry = _build_audit_entry(
        request_id=request_id,
        request=request,
        llm_response=llm_response,
        action_result=action_result,
        injection_result=injection_result,
        pii_prompt_result=pii_prompt_result,
        pii_response_result=pii_response_result,
        groundedness_result=groundedness_result,
        bias_result=bias_result,
        risk_score=risk_score,
        policy_decision=policy_decision,
        model_used=model_used,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        efficiency_result=efficiency_result,
        latency_ms=total_latency_ms,
        step_latencies=step_latencies,
    )

    logger.info(
        f"[{request_id}] Step 5 complete | "
        f"action={action_result.action} | "
        f"risk={risk_score.overall:.2f} ({risk_score.level}) | "
        f"total_latency={total_latency_ms}ms"
    )

    logger.info(
        f"Pipeline complete | request_id={request_id} | "
        f"action={action_result.action} | "
        f"latency={total_latency_ms}ms"
    )

    return action_result, audit_entry


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper Functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _classify_risk(
    injection_result: InjectionResult,
    pii_prompt: PIIResult,
    use_case: UseCase,
) -> RiskLevel:
    """
    Assigns preliminary risk level based on scan results.
    This classifier remains deliberately deterministic and explainable.

    Rules:
      - Any injection detected → HIGH
      - High-risk PII in prompt (SSN, credit card) → HIGH
      - Customer-facing use case + any PII → MEDIUM minimum
      - No signals → LOW
    """
    if injection_result.detected:
        return RiskLevel.HIGH
    if pii_prompt.found and any(
        e in pii_prompt.high_risk_entities
        for e in ["US_SSN", "CREDIT_CARD", "IBAN_CODE"]
    ):
        return RiskLevel.HIGH
    if pii_prompt.found and use_case == UseCase.CUSTOMER_CHATBOT:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _mock_risk_score(use_case: UseCase, level: RiskLevel) -> RiskScore:
    """Returns a mock risk score matching the given level."""
    overall_map = {
        RiskLevel.LOW: 0.2,
        RiskLevel.MEDIUM: 0.5,
        RiskLevel.HIGH: 0.8,
    }
    return RiskScore(
        overall=overall_map[level],
        level=level,
        breakdown=RiskBreakdown(dominant_signal="none"),
        use_case=use_case,
    )


def _mock_risk_score_high(use_case: UseCase) -> RiskScore:
    """Returns a HIGH mock risk score — used for injection early exit."""
    return _mock_risk_score(use_case, RiskLevel.HIGH)


def _build_audit_entry(
    request_id: str,
    request: InterceptRequest,
    llm_response: str,
    action_result: ActionResult,
    injection_result: InjectionResult,
    pii_prompt_result: PIIResult,
    pii_response_result: PIIResult,
    groundedness_result: GroundednessResult,
    bias_result: BiasResult,
    risk_score: RiskScore,
    policy_decision: PolicyDecision,
    model_used: str,
    tokens_input: int,
    tokens_output: int,
    latency_ms: int,
    step_latencies: dict[str, int],
    efficiency_result: Optional[EfficiencyResult] = None,
) -> AuditEntry:
    """
    Constructs the complete AuditEntry for one pipeline run.
    This gets written to PostgreSQL by the route-owned audit logger.
    """
    return AuditEntry(
        request_id=request_id,
        timestamp=datetime.now(timezone.utc),
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        use_case=request.use_case,
        session_id=request.session_id,
        prompt=request.prompt,
        prompt_length=len(request.prompt),
        llm_response=llm_response,
        model_used=model_used,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        tokens_total=tokens_input + tokens_output,
        estimated_cost_usd=(
            efficiency_result.estimated_cost_usd if efficiency_result else None
        ),
        efficiency=efficiency_result,
        final_response=action_result.final_response,
        injection=injection_result,
        pii_in_prompt=pii_prompt_result,
        pii_in_response=pii_response_result,
        groundedness=groundedness_result,
        bias=bias_result,
        risk_score=risk_score,
        policy_decision=policy_decision,
        action=action_result,
        latency_ms=latency_ms,
        step_latencies=step_latencies,
        escalation_required=action_result.escalation_required,
        human_reviewed=False,
    )
