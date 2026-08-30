# SentinelAI Phase History

This file is append-only. `phase.md` is the single source of truth for current
state; this log retains detailed completion history.

## 2026-08-30 — Phase 1 COMPLETE

Phase 1 established governance correctness and safety: verified PII redaction,
non-leaking escalation, risk-aware fail-safe policy behavior, detector
availability semantics, centralized risk thresholds, route-owned audit writes,
and a focused regression suite. The original detailed Phase 1 record remains in
`phase.md`, where it was recorded before this history file was introduced.

## 2026-08-30 — Phase 2 COMPLETE

### Scope and files

Created:

- `tests/test_phase2_groundedness_repair.py`
- `PHASE_HISTORY.md`

Modified:

- `api/schemas.py`
- `core/action_layer.py`
- `core/pipeline.py`
- `engines/trust/groundedness.py`
- `phase.md`

No database schema file changed; the existing action evidence mapping supports
the new repair audit fields.

### Implementation

- Introduced an explicit evidence verdict independent of detector operational
  status and enforced `status=UNAVAILABLE` if and only if
  `verdict=UNAVAILABLE`, while inferring the paired field for legacy callers.
- Added structured per-claim evidence and deterministic post-retrieval
  classification for material number mismatches, explicit negation/permission,
  inclusion, eligibility, requirements, categorical enablement/approval, and
  increase/decrease direction.
- Made low relevance and absent evidence insufficient rather than contradictory;
  made empty/non-checkable output insufficient rather than perfectly grounded.
- Applied conservative aggregation and public score mapping: supported `1.0`,
  insufficient `0.5`, contradicted `0.0`, unavailable `0.0`. Phase 1 retains its
  separate conservative risk contribution for unavailable verification.
- Implemented one bounded repair generation from the original question,
  original response, and cited local excerpts. It uses the existing pipeline LLM
  path with temperature at most `0.2` and a 400-token maximum, then performs one
  groundedness recheck. Only `SUPPORTED` is released as `REPAIR`; contradiction,
  insufficiency, unavailability, callback failure, missing evidence, and invalid
  repair preconditions are held as `ESCALATE`.
- Recorded repair attempts, counts, before/after verdicts, evidence source IDs and
  titles, flagged-claim count, and success in action evidence.
- Added a minimal policy guard without weakening configured BLOCK, ESCALATE, or
  REDACT decisions. Repairable contradictions use REPAIR; non-repairable
  contradictions and insufficient regulated evidence require review.

### Verification history

- Before Phase 2 edits: `python -m compileall -q .` exited `0` and `pytest -q`
  reported `191 passed, 18 warnings in 13.93s`.
- After the schema/classifier/repair changes:
  `pytest -q tests/test_phase1_governance.py` reported
  `21 passed, 18 warnings in 7.93s`.
- Initial focused Phase 2 run:
  `pytest -q tests/test_phase2_groundedness_repair.py` reported
  `13 passed, 6 warnings in 6.82s`.
- Initial full run: `pytest -q` reported
  `204 passed, 24 warnings in 12.60s`.
- Final required commands and their exact results are appended below after the
  final verification run.

The warnings are the existing Pydantic exposure of Python's
`datetime.utcnow()` deprecation during model construction; no tests were skipped
or failed.

### Limitations and preservation contract

The deterministic rules intentionally do not attempt open-ended semantic,
temporal, or causal reasoning. Verification still relies on the local embedding
model and Qdrant, with safe `UNAVAILABLE` behavior during outages. Repair is
limited to one evidence set and one attempt. Phase 3 must preserve detector
status/verdict separation, conservative aggregation, the one-call/one-recheck
bound, release-only-on-supported behavior, Phase 1 fail-safe actions and risk
thresholds, the route-owned single audit write, and all Phase 1/2 tests.

**Next phase:** Phase 3 — Real Efficiency Engine and Model Routing.

### Final required verification

- `.venv/bin/python -m compileall -q .`: exit `0`, no output.
- `.venv/bin/pytest -q tests/test_phase1_governance.py`:
  `21 passed, 18 warnings in 7.28s`.
- `.venv/bin/pytest -q tests/test_phase2_groundedness_repair.py`:
  `13 passed, 6 warnings in 6.82s`.
- `.venv/bin/pytest -q`: `204 passed, 24 warnings in 12.30s`.

### Final verification rerun

After isolating the repair system prompt from the normal use-case fact prompt,
the complete required verification was rerun:

- `.venv/bin/python -m compileall -q .`: exit `0`, no output.
- `.venv/bin/pytest -q tests/test_phase1_governance.py`:
  `21 passed, 18 warnings in 6.97s`.
- `.venv/bin/pytest -q tests/test_phase2_groundedness_repair.py`:
  `13 passed, 6 warnings in 6.91s`.
- `.venv/bin/pytest -q`: `204 passed, 24 warnings in 12.28s`.

## 2026-08-30 — Phase 3 COMPLETE

### Scope and exact files

Created:

- `config/models.yaml`
- `tests/test_phase3_efficiency_routing.py`

Modified:

- `api/routes/intercept.py`
- `api/schemas.py`
- `core/pipeline.py`
- `engines/efficiency/model_router.py`
- `phase.md`
- `PHASE_HISTORY.md`

No database schema changed. Structured efficiency data is carried by
`AuditEntry` and persisted within the existing action-evidence JSON path.

### Registry and routing implementation

The local YAML registry defines distinct ECONOMY, STANDARD, and PREMIUM routes
using `groq/openai/gpt-oss-20b`, `groq/openai/gpt-oss-120b`, and
`groq/qwen/qwen3.6-27b`. All pricing, capability, expected-latency, and
operational-context values are marked estimated/configurable rather than actual
billing or benchmark measurements. STANDARD is the counterfactual baseline.

The deterministic complexity estimator uses approximated input tokens, exact
token bands, question count, reasoning terms, structured/code-like input, risk,
and domain sensitivity. It makes no LLM call and returns LOW/MEDIUM/HIGH with
inspectable reasons.

The router derives required capability from risk, use case, and complexity. It
filters disabled profiles, unsupported use cases/risk levels, insufficient
capability, and inadequate context before optimizing. It selects the
lowest-estimated-cost safe profile within latency budget. When safe candidates
all exceed latency, it selects the fastest safe profile and reports the breach;
safety is never downgraded for speed or savings. With impossible combined
constraints, it returns the highest-capability enabled profile and enumerates
unmet constraints. All-disabled configuration fails explicitly.

Default estimated latency budgets are 700 ms for customer chat, 900 ms for HR,
and 1,200 ms for finance. Positive request-level overrides are supported.

### Cost and efficiency implementation

Token estimation is `ceil(non-whitespace characters / 4)`. Estimated request
cost is:

`(input tokens × input price per 1M + output tokens × output price per 1M) / 1,000,000`.

Savings equal baseline estimated cost minus selected estimated cost and may be
negative when governance requires a stronger route. A zero-cost baseline yields
zero savings percentage instead of division failure.

New schemas include `ModelTier`, `ComplexityLevel`, `ModelProfile`,
`ComplexityAssessment`, `RoutingResult`, and `EfficiencyResult`. The efficiency
result contains model-fit, cost, latency and overall scores; selected/baseline
models; estimated costs and savings; expected/observed latency; budget breach;
required/selected capability; retry count; and explanations. Fit has 50% weight,
cost and latency 25% each, plus a capability gate so cheap under-capable routes
cannot score well.

The pipeline routes before generation, evaluates efficiency without another LLM
call, retains compatibility with legacy two-argument router plugins, exposes the
result in API output and action evidence, and includes it in AuditEntry. Phase 2
repair continues to reuse the routed generation path with its existing one-call,
one-recheck bound.

### Tests and test-quality audit

`tests/test_phase3_efficiency_routing.py` contributes 32 offline cases. They
cover each tier, HIGH finance/HR safety, long LOW traffic, short HIGH traffic,
latency conflicts, token and context boundaries, zero/large/output-heavy costs,
baseline and negative savings, close candidates with reversed registry order,
disabled/all-disabled profiles, impossible constraints, model-fit gating, actual
latency overrun, and pipeline audit/evidence with exactly one normal generation.

The tests are not happy-path-only and were derived from product invariants. Each
tier must win at least one case. Cheapest is deliberately wrong for HIGH HR and
finance; PREMIUM is deliberately wasteful for simple LOW and long but
non-sensitive traffic. Exact boundaries, conflicts, and failures are present.
An always-PREMIUM implementation fails ECONOMY/STANDARD, savings, disabled, and
ordering cases. An always-ECONOMY implementation fails regulated capability,
domain approval, complexity, disabled, and context cases.

### Exact verification results

Before Phase 3 edits:

- `.venv/bin/python -m compileall -q .`: exit `0`, no output.
- `.venv/bin/pytest -q`: `204 passed, 24 warnings in 12.15s`.

Final required verification:

- `.venv/bin/python -m compileall -q .`: exit `0`, no output.
- `.venv/bin/pytest -q tests/test_phase1_governance.py`:
  `21 passed, 18 warnings in 7.08s`.
- `.venv/bin/pytest -q tests/test_phase2_groundedness_repair.py`:
  `13 passed, 6 warnings in 7.04s`.
- `.venv/bin/pytest -q tests/test_phase3_efficiency_routing.py`:
  `32 passed in 7.09s`.
- `.venv/bin/pytest -q`: `236 passed, 24 warnings in 12.78s`.

The warnings are the pre-existing Pydantic exposure of `datetime.utcnow()`
deprecation. No tests failed or were skipped.

### Decisions, limitations, and preservation contract

Capability and policy precede cost/latency. Estimated values remain explicitly
labeled and negative savings are truthful governance tradeoffs. The router does
not alter Phase 1 policy/action outcomes or Phase 2 groundedness/repair behavior.

Token/output estimates are approximate; provider billing is not queried.
Expected latency and capability are planning metadata, and observed latency is
local route-plus-generation time rather than provider-only latency. Initial-route
cost does not yet add Phase 2 repair token cost, though retry count is exposed.
Registry availability is configured rather than fetched from live provider
permissions, so identifiers and pricing require maintenance. Existing
preliminary risk classification remains authoritative router input.

Phase 4 must preserve capability-first routing, explicit constraint breaches,
estimated-versus-actual labels, deterministic arithmetic, all three routes, no
extra complexity LLM call, Phase 1 fail-safe actions, Phase 2 bounded repair,
route-owned single audit persistence, and every Phase 1–3 regression. Escalated
original content must remain internal when authorized review access is added.

**Next phase:** Phase 4 — Human Review and Feedback Loop.

## 2026-08-30 — Phase 3 post-review correction COMPLETE

### Issue and scope

Review found that `route_model()` could return a best-available candidate with
unmet capability, risk-policy, context-window, or use-case constraints, and the
pipeline could still send that candidate to `_call_llm`. This correction changes
only Phase 3 routing preflight behavior. Phase 4 was not started.

Modified:

- `api/schemas.py`
- `core/pipeline.py`
- `engines/efficiency/model_router.py`
- `tests/test_phase3_efficiency_routing.py`
- `phase.md`
- `PHASE_HISTORY.md`

### Implementation

`RoutingConstraint` now gives constraints typed names. The centralized hard set
contains `capability_requirement`, `risk_policy`, `context_window`, and
`use_case_support`; `latency_budget` is soft. `hard_routing_failures()` and
`has_hard_routing_failure()` are the only classification helpers.

`RoutingResult` now records canonical `unmet_constraints`,
`generation_approved`, `routing_failure`, and selected context capacity. A
compatibility property retains the original `constraints_unmet` accessor. The
router still returns its best candidate for observability, but any hard failure
sets generation approval false. Latency alone does not.

Immediately after routing, the pipeline checks the centralized helper. For a hard
failure it returns an ESCALATE holding response before any provider call, records
an empty LLM response, zero generation tokens, zero generation cost, and
`model_used=none`. Evidence names the fallback candidate while explicitly
recording `candidate_approved_for_generation=false`, all hard/full constraints,
routing reason, use case, risk, capability, token estimate, and context capacity.
The route-owned audit behavior remains unchanged.

`EfficiencyResult.generation_performed` differentiates projected candidates from
real calls. A blocked preflight uses zero estimated generation cost/savings. A
safe latency-only breach proceeds using the capable model and retains the breach
evidence; safety/capability remains more important than latency.

### Tests and exact results

Five product-level pipeline cases were added with `AsyncMock` provider-call
assertions:

- HIGH finance with only ECONOMY enabled does not call the LLM and escalates.
- HIGH HR with under-capable models does not call the LLM and escalates.
- Context larger than every enabled model does not call the LLM and escalates.
- A safe PREMIUM latency-only breach still calls the LLM without downgrade.
- A fully satisfied LOW route preserves normal generation.

Earlier route tests now assert approval/failure semantics for under-capability,
impossible context, and latency-only cases. Phase 3 contains 37 cases after the
correction.

Baseline before correction:

- `.venv/bin/python -m compileall -q .`: exit `0`, no output.
- `.venv/bin/pytest -q`: `236 passed, 24 warnings in 12.47s`.

Final required verification:

- `.venv/bin/python -m compileall -q .`: exit `0`, no output.
- `.venv/bin/pytest -q tests/test_phase3_efficiency_routing.py`:
  `37 passed, 3 warnings in 7.19s`.
- `.venv/bin/pytest -q tests/test_phase1_governance.py`:
  `21 passed, 18 warnings in 7.15s`.
- `.venv/bin/pytest -q tests/test_phase2_groundedness_repair.py`:
  `13 passed, 6 warnings in 6.97s`.
- `.venv/bin/pytest -q`: `241 passed, 27 warnings in 12.82s`.

Warnings remain the existing Pydantic exposure of `datetime.utcnow()`
deprecation. No tests failed or were skipped.

### Preservation contract

Phase 4 must preserve the hard/soft split, pre-generation fail-closed behavior,
empty/non-leaking LLM record, zero call tokens/cost on routing failure, explicit
candidate-versus-approval audit evidence, safe latency-only generation, Phase 1
actions and risk thresholds, Phase 2 bounded repair, and every Phase 1–3 test.

**Current phase:** Phase 3 — COMPLETE
**Next phase:** Phase 4 — Human Review and Feedback Loop (not started).

## 2026-08-30 — Phase 4 COMPLETE

Phase 4 added a durable PostgreSQL human-review queue, internal reviewer detail,
atomic decisions, public-safe resolution polling, durable feedback, and review
metrics without changing completed Phase 1–3 governance behavior.

Created `api/routes/reviews.py`, `api/routes/feedback.py`,
`data/review_store.py`, and `tests/test_phase4_human_review.py`. Modified
`api/routes/intercept.py`, `api/schemas.py`, `core/main.py`, `data/schema.sql`,
`phase.md`, and this append-only history.

Only final ESCALATE actions enqueue. The database unique request key plus
`ON CONFLICT (request_id) DO NOTHING` makes retries idempotent. Queue failures
are logged while the safe holding response remains public. Internal review
records include held output, policy/action evidence, groundedness/source data,
and routing/efficiency data; list summaries and public resolutions use separate
non-leaking schemas.

Decisions use an atomic pending-only UPDATE with RETURNING. APPROVE releases the
held original, EDIT requires and releases a nonblank reviewer edit, and REJECT
returns a fixed safe response. The same transaction writes exactly one feedback
record using APPROVE→ALLOW, EDIT→REPAIR, and REJECT→ESCALATE. PostgreSQL remains
the review authority and audit rows are not mutated.

Review metrics report totals, status counts, completion, override, and agreement
rates with zero-safe denominators. Manual feedback rejects unknown audit IDs and
never changes learning, policy, thresholds, or runtime behavior.

The 34-case Phase 4 suite includes an actual hard-routing failure that asserts no
LLM call, zero generation tokens, routing evidence, and review enqueue. It also
covers all actions, duplicate/failing enqueue, filtering, evidence, every
decision and resolution, blank edits, missing IDs, sequential/concurrent races,
non-leakage, feedback mappings, metrics, persistence invariants, and routes.

Verification completed with compile exit `0`; Phase 1 `21 passed, 18 warnings`;
Phase 2 `13 passed, 6 warnings`; Phase 3 `37 passed, 3 warnings`; Phase 4
`34 passed, 10 warnings`; and full suite `275 passed, 37 warnings`. The warnings
are the existing Pydantic `datetime.utcnow()` deprecation; no failures or skips.

Known limitations intentionally left for Phase 5 include reviewer/tenant auth,
raw-content privacy and retention, live PostgreSQL integration verification, and
an operational retry/outbox for failed enqueue. Resolution is intentionally
pull-based and feedback does not automatically learn.

**Current phase:** Phase 4 — COMPLETE
**Next phase:** Phase 5 — Enterprise Hardening and Claim Cleanup (not started).
