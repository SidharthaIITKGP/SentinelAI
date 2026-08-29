"""
SentinelAI — Central Pipeline Orchestrator

The heart of SentinelAI. Every request flows through run_pipeline().
Orchestrates the 5-step governance pipeline:
  Step 1 — SCAN:           detect injection + PII in incoming prompt
  Step 2 — CLASSIFY:       assign risk level based on scan results
  Step 3 — ROUTE+GENERATE: pick the right LLM model, call it, get response
  Step 4 — EVALUATE:       run 3 engines IN PARALLEL on the LLM response
  Step 5 — ACT+LOG:        take governed action, write to audit log

External dependencies (stubbed until Day 3):
  Aman:   pii_detector, bias_detector, policy/engine
  Gaurav: model_router, audit_logger
  Self:   injection_detector, groundedness, risk_scorer, action_layer
"""

from __future__ import annotations

import asyncio
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
    GroundednessResult,
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


# ── Sidhartha's own engine modules (stubbed until Day 2) ──────────────────────
try:
    from core.injection_detector import scan as injection_scan
except ImportError:
    injection_scan = None
    logger.warning("injection_detector not found — stubbed")

try:
    from engines.trust.groundedness import check as groundedness_check
except ImportError:
    groundedness_check = None
    logger.warning("groundedness not found — stubbed")

try:
    from core.risk_scorer import compute as compute_risk
except ImportError:
    compute_risk = None
    logger.warning("risk_scorer not found — stubbed")

try:
    from core.action_layer import execute as execute_action
except ImportError:
    execute_action = None
    logger.warning("action_layer not found — stubbed")

# ── Aman's modules (stubbed until Day 3) ──────────────────────────────────────
try:
    from engines.responsibility.pii_detector import detect_pii
except ImportError:
    detect_pii = None
    logger.warning("pii_detector not found — stubbed (Aman's module)")

try:
    from engines.responsibility.bias_detector import detect_bias
except ImportError:
    detect_bias = None
    logger.warning("bias_detector not found — stubbed (Aman's module)")

try:
    from policy.engine import evaluate_policy
except ImportError:
    evaluate_policy = None
    logger.warning("policy engine not found — stubbed (Aman's module)")

# ── Gaurav's modules (stubbed until Day 3) ────────────────────────────────────
try:
    from engines.efficiency.model_router import route_model
except ImportError:
    route_model = None
    logger.warning("model_router not found — stubbed (Gaurav's module)")

try:
    from data.audit_logger import log_request
except ImportError:
    log_request = None
    logger.warning("audit_logger not found — stubbed (Gaurav's module)")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Mock LLM call (stubbed until Day 3 — real LiteLLM integration)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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
        logger.error(f"LLM call failed | model={model} | error={str(e)}")
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
    """Mock injection result — no injection detected."""
    return InjectionResult(detected=False, confidence=0.0, method="none")


def _mock_pii_result(scan_target: str = "prompt") -> PIIResult:
    """Mock PII result — no PII found."""
    return PIIResult(found=False, risk_score=0.0, scan_target=scan_target)


def _mock_bias_result() -> BiasResult:
    """Mock bias result — no bias detected."""
    return BiasResult(
        detected=False, score=0.0, confidence=0.0, detection_method="pattern_match"
    )


def _mock_groundedness_result(use_case: UseCase) -> GroundednessResult:
    """Mock groundedness result — fully grounded."""
    return GroundednessResult(
        score=1.0,
        total_claims_checked=1,
        grounded_claims_count=1,
        use_case_kb_used=use_case,
    )


def _mock_policy_decision() -> PolicyDecision:
    """Mock policy decision — approved, ALLOW action."""
    return PolicyDecision(
        approved=True,
        final_action=ActionType.ALLOW,
        reason="Policy engine stubbed — defaulting to ALLOW",
        policy_file="stub",
        threshold_applied=0.75,
    )


def _mock_model_config() -> dict:
    """Default model config — Groq Qwen 3.8 27B (2M tokens/day free tier)."""
    return {
        "model": "groq/qwen/qwen3.8-27b",
        "max_tokens": 200,
        "temperature": 0.3,
        "reason": "Default — Groq Qwen 3.8 27B",
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
    # REAL (Day 2): injection_result = await injection_scan(request.prompt)
    if injection_scan is not None:
        injection_result = await injection_scan(request.prompt)
    else:
        injection_result = _mock_injection_result()
        logger.debug(f"[{request_id}] injection_scan stubbed")

    # Early exit: critical injection → immediate BLOCK
    if injection_result.detected and injection_result.confidence > 0.90:
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
            risk_score=_mock_risk_score_high(request.use_case),
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

    # PII scan on prompt (Aman's module)
    # REAL (Day 3): pii_prompt_result = await detect_pii(request.prompt)
    if detect_pii is not None:
        pii_prompt_result = await detect_pii(request.prompt)
    else:
        pii_prompt_result = _mock_pii_result("prompt")
        logger.debug(f"[{request_id}] detect_pii (prompt) stubbed — Aman's module")

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

    # TODO Day 2: implement more sophisticated classification logic
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

    # Model routing (Gaurav's module)
    # REAL (Day 3): model_config = route_model(preliminary_risk_level, request.use_case)
    if route_model is not None:
        model_config = route_model(preliminary_risk_level, request.use_case)
    else:
        model_config = _mock_model_config()
        logger.debug(f"[{request_id}] route_model stubbed — Gaurav's module")

    # LLM call
    llm_response, tokens_input, tokens_output = await _call_llm(
        prompt=request.prompt,
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
        f"latency={step_latencies['generate']}ms"
    )

    # ──────────────────────────────────────────────────────────────────────
    # STEP 4 — EVALUATE (3 engines run IN PARALLEL)
    # Run all 3 evaluation engines simultaneously using asyncio.gather.
    # This is critical for latency — running sequentially would be 3x slower.
    #
    # Engine A: groundedness.py    → is the response factually grounded?
    # Engine B: pii_detector.py    → does the response contain PII? (Aman)
    # Engine C: bias_detector.py   → does the response contain bias? (Aman)
    #
    # REAL (Day 3):
    # groundedness_result, pii_response_result, bias_result = await asyncio.gather(
    #     groundedness_check(llm_response, request.use_case),
    #     detect_pii(llm_response),           # Aman's module — scan RESPONSE
    #     detect_bias(llm_response),          # Aman's module
    # )
    # ──────────────────────────────────────────────────────────────────────
    step_start = time.time()
    logger.info(f"[{request_id}] Step 4: EVALUATE starting (parallel engines)...")

    # Run engines — use real if available, mock if not
    async def _run_groundedness():
        """Run groundedness check or return mock."""
        if groundedness_check is not None:
            return await groundedness_check(llm_response, request.use_case)
        logger.debug(f"[{request_id}] groundedness_check stubbed")
        return _mock_groundedness_result(request.use_case)

    async def _run_pii_response():
        """Run PII scan on LLM response or return mock."""
        if detect_pii is not None:
            result = await detect_pii(llm_response)
            result.scan_target = "response"
            return result
        logger.debug(
            f"[{request_id}] detect_pii (response) stubbed — Aman's module"
        )
        return _mock_pii_result("response")

    async def _run_bias():
        """Run bias detection or return mock."""
        if detect_bias is not None:
            return await detect_bias(llm_response)
        logger.debug(f"[{request_id}] detect_bias stubbed — Aman's module")
        return _mock_bias_result()

    # THE KEY LINE — all 3 run simultaneously, not sequentially
    groundedness_result, pii_response_result, bias_result = await asyncio.gather(
        _run_groundedness(),
        _run_pii_response(),
        _run_bias(),
    )

    step_latencies["evaluate"] = int((time.time() - step_start) * 1000)
    logger.info(
        f"[{request_id}] Step 4 complete | "
        f"groundedness={groundedness_result.score:.2f} | "
        f"pii_in_response={pii_response_result.found} | "
        f"bias={bias_result.detected} | "
        f"latency={step_latencies['evaluate']}ms"
    )

    # ──────────────────────────────────────────────────────────────────────
    # STEP 5 — ACT + LOG
    # Combine all engine results into a risk score.
    # Get policy decision from OPA (Aman's module).
    # Execute the governed action.
    # Log everything to audit trail (non-blocking).
    # ──────────────────────────────────────────────────────────────────────
    step_start = time.time()
    logger.info(f"[{request_id}] Step 5: ACT + LOG starting...")

    # Risk scoring
    # REAL (Day 2): risk_score = compute_risk(injection_result, pii_prompt_result, ...)
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
        logger.debug(f"[{request_id}] compute_risk stubbed")

    # Policy evaluation (Aman's OPA module)
    # REAL (Day 3): policy_decision = await evaluate_policy(request.use_case, risk_score)
    if evaluate_policy is not None:
        policy_decision = await evaluate_policy(
            use_case=request.use_case,
            risk_score=risk_score,
            pii_detected=pii_response_result.found,
            bias_detected=bias_result.detected,
            secrets_detected=False,
        )
    else:
        policy_decision = _mock_policy_decision()
        logger.debug(f"[{request_id}] evaluate_policy stubbed — Aman's module")

    # Action execution
    # REAL (Day 2): action_result = await execute_action(policy_decision, risk_score, ...)
    if execute_action is not None:
        action_result = await execute_action(
            policy_decision=policy_decision,
            risk_score=risk_score,
            llm_response=llm_response,
            pii_in_response=pii_response_result,
            use_case=request.use_case,
        )
    else:
        action_result = ActionResult(
            action=policy_decision.final_action,
            final_response=llm_response,
            original_response=llm_response,
            explanation="Action layer stubbed — defaulting to policy decision",
            evidence={
                "risk_score": risk_score.overall,
                "risk_level": risk_score.level,
                "policy_reason": policy_decision.reason,
            },
        )
        logger.debug(f"[{request_id}] execute_action stubbed")

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
        latency_ms=total_latency_ms,
        step_latencies=step_latencies,
    )

    # Non-blocking audit log write
    # REAL (Day 3): asyncio.create_task(log_request(audit_entry))
    if log_request is not None:
        asyncio.create_task(log_request(audit_entry))
    else:
        logger.debug(f"[{request_id}] audit_logger stubbed — Gaurav's module")

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
    TODO Day 2: expand with more sophisticated logic.

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
) -> AuditEntry:
    """
    Constructs the complete AuditEntry for one pipeline run.
    This gets written to PostgreSQL by audit_logger.py (Gaurav's module).
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
