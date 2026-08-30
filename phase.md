# SentinelAI Remediation Plan

## Goal

Upgrade the existing SentinelAI Round 2 prototype in-place from a strong but incomplete prototype into a judge-ready, defensible implementation without replacing the architecture or starting over.

The implementation must remain aligned with the existing five-stage pipeline:

1. Scan
2. Classify
3. Optimize + Route
4. Evaluate
5. Act + Learn

The priority is correctness, demonstrability, measurable evidence, and consistency between what the product claims and what the code actually does.

---

## Current Status

**Current phase:** Phase 1 — COMPLETE  
**Completed phases:** Phase 1 — Governance correctness and safety  
**Next phase:** Phase 2 — Groundedness uncertainty and real repair

### Baseline verification observed on 2026-08-30

- `python -m compileall -q .` exited `127` because the host initially had no `python` command on `PATH`.
- `pytest -q` exited `127` because the host initially had no `pytest` command on `PATH`.
- `python3 -m compileall -q .` exited `0` before edits.
- The workspace contained an ignored pre-existing `tests/` tree, but no runnable Python environment. A workspace-local `.venv` was created and the declared dependencies plus `en_core_web_sm` were installed for verification.

---

## Baseline Limitations

### P0 correctness problems resolved in Phase 1

- REDACT currently replaces `PIIEntity.text`, but that field intentionally contains safe placeholders rather than the raw sensitive substring, so integrated redaction can fail to remove the real PII.
- ESCALATE currently returns the original LLM response while merely setting `escalation_required=True`; that violates the promised pre-delivery human-review gate.
- Policy-engine exceptions currently fail open to `ALLOW`.
- Some detector failures are represented as a clean/safe result instead of an unavailable/unknown state.
- Groundedness-unavailable behavior can be interpreted as fully grounded.
- Risk thresholds are duplicated and contradictory between `core/risk_scorer.py` and the `RiskScore` schema validator.
- The pipeline and `/intercept` route both attempt to write the same audit entry.
- There is no automated regression suite protecting the governance actions.

### P1 capability gaps

- REPAIR is still a stub.
- Model routing currently points both default and premium routes to the same model.
- Cost/latency/model-fit evaluation is not yet a real Efficiency Engine.
- Human review and feedback schemas exist, but there is no complete review/feedback workflow.
- Multi-turn/session risk is not implemented.
- Audit persistence retains raw prompt/response content by default.
- Tenant authentication is claimed conceptually but not implemented.
- `/health` reports hard-coded dependency states.
- Redis is provisioned but not meaningfully used.
- OPA and OpenTelemetry are mentioned in architecture/context but are not actually integrated in the executable prototype.
- Evaluation metrics such as precision, recall, false-positive rate, false-negative rate, action accuracy, and P95 governance latency are missing.

---

# Phase Roadmap

## Phase 1 — Governance Correctness and Safety

### Objective
Make the existing decisions safe and internally consistent before adding features.

### Must implement
- Fix REDACT using the existing Presidio anonymization path or reliable offsets.
- Make ESCALATE hold the original response instead of releasing it.
- Change policy failure from fail-open to risk/use-case-aware fail-safe behavior.
- Introduce explicit detector availability/unknown semantics where required, without pretending failure means safe.
- Unify risk-level thresholds into one source of truth.
- Remove duplicate audit persistence.
- Add automated unit/integration tests for all P0 behaviors.
- Preserve existing public API compatibility where reasonably possible.

### Exit criteria
- `python -m compileall -q .` passes.
- `pytest -q` passes.
- Tests prove:
  - ALLOW returns original output.
  - BLOCK never returns original output.
  - REDACT removes actual PII.
  - ESCALATE does not expose original output.
  - policy failure never silently ALLOWs a high-risk regulated request.
  - exact boundary tests for LOW/MEDIUM/HIGH thresholds.
  - one audit write per request.
- No Phase 2 work is started before these criteria pass.

### Expected files likely changed
- `api/schemas.py`
- `core/risk_scorer.py`
- `core/action_layer.py`
- `core/pipeline.py`
- `policy/engine.py`
- `api/routes/intercept.py`
- responsibility detector wrappers as needed
- new `tests/` files
- `phase.md`

---

## Phase 2 — Groundedness Uncertainty and Real Repair

### Objective
Turn trust evaluation from similarity-only behavior into an evidence-aware, uncertainty-safe workflow and make REPAIR real.

### Must implement
- Represent groundedness status explicitly, at minimum:
  - `SUPPORTED`
  - `CONTRADICTED`
  - `INSUFFICIENT_EVIDENCE`
  - `UNAVAILABLE`
- Never map unavailable verification to a perfect groundedness score.
- Add a practical contradiction check after retrieval. Prefer a lightweight NLI/LLM-judge adapter only if it can be deterministic, bounded, and tested; otherwise implement a transparent evidence heuristic and label its limitation.
- Implement one bounded REPAIR cycle:
  - retrieve supporting evidence,
  - regenerate constrained by evidence,
  - re-evaluate repaired response,
  - ALLOW repaired output only if it passes,
  - otherwise ESCALATE/BLOCK according to policy.
- Prevent infinite repair loops.
- Add tests for supported, contradicted, insufficient-evidence, unavailable, successful repair, failed repair.

### Exit criteria
- All Phase 1 tests continue to pass.
- New trust/repair tests pass.
- A demo case can show a wrong factual claim being repaired using cited local knowledge-base evidence.

---

## Phase 3 — Real Efficiency Engine and Model Routing

### Objective
Make the third ControlPlane dimension, efficiency, a real implemented capability.

### Must implement
- Add a model registry/config with at least two distinct model tiers or simulated provider profiles.
- Route using use case, risk, estimated complexity/token count, latency budget, and policy.
- Calculate:
  - selected model,
  - baseline model,
  - estimated input/output cost,
  - estimated savings,
  - actual/estimated latency,
  - budget breach flag.
- If only one real provider credential is available, support deterministic simulated pricing/latency metadata while clearly labeling it as estimated.
- Populate existing cost fields rather than leaving them empty.
- Add efficiency result to audit/evidence and dashboard/API payloads.
- Add tests proving different inputs can select different routes and that cost calculations are deterministic.

### Exit criteria
- At least two materially different routes are demonstrable.
- Dashboard/API can show why a model was selected and estimated savings.
- Existing phases remain green.

---

## Phase 4 — Human Review and Feedback Loop

### Objective
Complete the "Act + Learn" part of SentinelAI.

### Must implement
- Add pending-review storage/query.
- Add review API:
  - list pending,
  - approve,
  - edit,
  - reject.
- Original escalated content must only be available to the authorized review workflow, not returned to the end-user response.
- Add feedback endpoint using the existing feedback schemas/table.
- Persist reviewer, outcome, timestamp, notes/corrected action.
- Add simple evaluation metrics:
  - review count,
  - override rate,
  - SentinelAI/reviewer agreement rate.
- Do not automatically train model weights.
- If suggesting threshold changes, keep them recommendation-only unless explicitly approved.

### Exit criteria
- End-to-end demo: ESCALATE → pending review → approve/edit/reject → audit/feedback updated.
- Tests cover the workflow.

---

## Phase 5 — Enterprise Hardening and Claim Cleanup

### Objective
Make the implementation defensible under technical questioning.

### Must implement
- Add minimal tenant authentication, e.g. API key → tenant mapping, while keeping local/demo configuration simple.
- Stop trusting arbitrary client-supplied `tenant_id` when authentication is enabled.
- Add privacy-aware audit mode:
  - redacted prompt/response by default,
  - hashes/metadata,
  - configurable raw-content retention only for demo/debug.
- Implement real health checks only for dependencies actually used.
- Remove unused dependency claims/services or wire them meaningfully.
- Either:
  - implement OPA/OpenTelemetry/Redis for a specific real purpose, or
  - rename documentation/deck-facing claims to what actually exists, e.g. "policy-as-code YAML prototype; OPA-ready production adapter".
- Tighten CORS via environment configuration.
- Remove stale "Day 2/Day 3/stubbed" comments from production paths where functionality is complete.
- Clean API naming and dev-only routes if needed.

### Exit criteria
- No architecture slide/demo claim materially contradicts the code.
- Health endpoint truthfully reflects actual dependencies.
- Sensitive content is not unnecessarily persisted.

---

## Phase 6 — Benchmark, Demo Readiness, and Winning Evidence

### Objective
Turn the prototype into a measurable competition submission.

### Must implement
- Add a labeled benchmark dataset with realistic clean and risky examples across:
  - prompt injection,
  - PII/secrets,
  - bias,
  - hallucination/groundedness,
  - ambiguity,
  - normal clean traffic.
- Include all three use cases.
- Add an offline benchmark runner that reports:
  - precision,
  - recall,
  - F1,
  - false-positive rate,
  - false-negative rate,
  - action accuracy,
  - average and P95 governance latency,
  - LLM calls avoided,
  - estimated cost avoided/saved.
- Do not invent performance numbers. Only display values produced by the benchmark.
- Prepare deterministic demo fixtures for:
  1. ALLOW clean request
  2. pre-LLM BLOCK injection
  3. REDACT PII
  4. REPAIR contradicted claim
  5. ESCALATE regulated ambiguity and human review
  6. model route/cost optimization
- Add a compact Governance Receipt to API/demo output with request ID, policy/rule, checks, decision, evidence references, model, latency, and estimated cost.

### Exit criteria
- One command runs the benchmark and prints/saves results.
- One documented demo flow exercises the major actions.
- All automated tests pass.

---

# Change Log

## 2026-08-30 — Phase 1 COMPLETE

### Files created

- `core/risk_thresholds.py`
- `tests/test_phase1_governance.py`
- `phase.md`

### Files modified

- `.gitignore`
- `api/routes/intercept.py`
- `api/schemas.py`
- `core/action_layer.py`
- `core/pipeline.py`
- `core/risk_scorer.py`
- `engines/responsibility/bias_check/bias_config.json`
- `engines/responsibility/bias_detector.py`
- `engines/responsibility/pii_detector.py`
- `engines/trust/groundedness.py`
- `policy/engine.py`

### Behaviors fixed

- REDACT now invokes the existing Presidio anonymization wrapper, supplements it with safe local pattern offsets for structured values, verifies detected spans are absent, and changes to ESCALATE if redaction is unavailable or incomplete. Evidence contains only entity categories/counts.
- ESCALATE returns a use-case holding message and retains the original response only in the internal `ActionResult`/audit record. `ActionResult` rejects an escalated result whose final output equals the original.
- Policy evaluator failures use explicit local fail-safe rules. High-risk customer traffic blocks; high-risk HR/finance traffic escalates; explicit injection/secrets never allow; explicit PII redacts when safe; regulated unknowns hold; only clean LOW customer traffic can receive a labeled degraded ALLOW.
- Added backward-compatible `DetectorStatus` fields with default `AVAILABLE` to injection, PII, bias, and groundedness results. Detector wrapper failures return `UNAVAILABLE`, not a clean verdict.
- Groundedness unavailability now returns `status=UNAVAILABLE`, `score=0.0`, and zero verified claims. Risk scoring uses use-case-specific conservative unknown contributions.
- LOW/MEDIUM/HIGH boundaries now come only from `core/risk_thresholds.py`: LOW `<= 0.20`, MEDIUM `> 0.20 and <= 0.55`, HIGH `> 0.55`. The schema validates and rejects conflicts instead of rewriting levels.
- Audit persistence is owned solely by the `/intercept` route; `run_pipeline` only returns the audit record, including early-block paths.
- Safe bias observations below the verdict threshold remain available as evidence instead of being erased, and the configured explicit-pattern minimum is consistently enforced at `0.80`.

### Tests added

`tests/test_phase1_governance.py` adds 21 focused cases covering:

- unchanged ALLOW and non-leaking BLOCK;
- email and SSN redaction using category placeholders;
- redaction failure hold;
- ESCALATE holding and schema invariant;
- exact `0.20`, just-above-`0.20`, `0.55`, and just-above-`0.55` boundaries;
- conflicting risk-level rejection;
- policy-engine exception fallback for low customer, medium HR, and high finance traffic;
- explicit PII during policy failure;
- degraded customer and regulated detector-availability guards;
- PII/bias detector exception semantics;
- groundedness unavailable score/risk behavior;
- one audit write through the `/intercept` endpoint function with a real mocked pipeline run.

The Starlette/FastAPI synchronous `TestClient` portal thread did not shut down in this sandbox. The audit integration test therefore calls the FastAPI endpoint function directly; the repository's existing async `httpx.ASGITransport` endpoint tests pass.

### Commands and results

- Baseline `python -m compileall -q .`: exit `127` (`python` unavailable).
- Baseline `pytest -q`: exit `127` (`pytest` unavailable).
- Baseline `python3 -m compileall -q .`: exit `0`.
- Initial focused Phase 1 run: `19 passed, 16 warnings in 0.26s`.
- First full run after dependencies but before the spaCy model: `122 passed, 11 failed, 56 errors, 16 warnings in 12.17s`; missing `en_core_web_sm` caused the errors.
- Full run after installing the spaCy model: `183 passed, 6 failed, 16 warnings in 7.40s`; the six failures exposed the bias evidence/threshold inconsistency fixed above.
- Final `python -m compileall -q .`: exit `0`, no output.
- Final `pytest -q`: `191 passed, 18 warnings in 12.67s`.
- All 18 warnings are the existing Pydantic exposure of Python's `datetime.utcnow()` deprecation from Phase 1 test model construction; no tests are skipped or failed.

### Remaining known limitations

- REPAIR remains the existing stub; no Phase 2 repair logic was implemented.
- Groundedness has only Phase 1 availability semantics. `SUPPORTED`, `CONTRADICTED`, and `INSUFFICIENT_EVIDENCE` remain Phase 2 work.
- Model routing/efficiency, human review queue and feedback workflow, tenant authentication, privacy-aware audit retention, truthful dependency health checks, infrastructure claim cleanup, and benchmarking remain assigned to Phases 3–6.
- Internal audit persistence still retains raw prompt/response content by default; this is explicitly deferred to Phase 5.
- The project dependency set remains heavyweight and the configured spaCy model must be installed for the full legacy responsibility suite.

### Phase 2 design constraints to preserve

- Extend the existing detector-status model rather than removing the backward-compatible `AVAILABLE`/`UNAVAILABLE` contract.
- Preserve the single authoritative risk boundaries and route-owned one-write audit model.
- Keep escalated original content internal; never expose it in `InterceptResponse.final_response`.
- REPAIR must be one bounded evidence-constrained attempt, re-evaluated before release, with no infinite loop.
- Unavailable verification must remain distinct from unsupported or contradicted evidence and must never become a perfect groundedness score.

**Next phase:** Phase 2 — Groundedness uncertainty and real repair. Do not begin without review/authorization.
