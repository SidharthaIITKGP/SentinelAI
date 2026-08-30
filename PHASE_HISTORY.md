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
