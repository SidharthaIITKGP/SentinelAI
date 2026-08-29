# Bias Detection Work

## Purpose

Detect biased or discriminatory LLM responses and return structured evidence. `BiasDetector` does not decide `ALLOW`, `BLOCK`, or `ESCALATE`; `PolicyEngine` owns those actions.

## Architecture

```text
LLM response
  -> explicit rules
  -> fairness trigger -> semantic analysis -> optional LLM judge
  -> toxicity / identity-hate support
  -> per-sentence context adjustment
  -> non-averaging evidence aggregation
  -> BiasResult
  -> PolicyEngine
```

The fairness trigger only routes protected-group decision/treatment language. Toxicity cannot establish bias alone. The optional LLM judge is disabled by default and returns evidence only.

## File | Purpose

| File | Purpose |
|---|---|
| `__init__.py` | Exposes the detector and cached factory. |
| `bias_detector.py` | Orchestrates signals and builds `BiasResult`. |
| `bias_fairness.py` | Finds fairness-sensitive decisions without declaring bias. |
| `bias_llm_judge.py` | Validates optional structured LLM evidence. |
| `bias_config.json` | Stores models, rules, references, terms, and thresholds. |
| `bias_validation.json` | Holds the deterministic evaluation cases. |
| `evaluate_bias.py` | Reports precision, recall, F1, FPR, and FNR. |
| `work.md` | Summarizes this phase. |
| `tests/bias_check/` | Contains local detector, API, policy, and LLM regression tests. |
| `api/schemas.py` | Defines shared bias and LLM-judgment data contracts. |
| `api/routes/responsibility.py` | Exposes `POST /responsibility/bias/scan`. |
| `pii_check/policy/engine.py` | Applies policy to the detector result. |

## Models and thresholds

- Toxicity: `unitary/toxic-bert`, supporting signal only.
- Semantics: `all-MiniLM-L6-v2`, cached reference embeddings.
- Semantic threshold: `0.65`; final bias threshold: `0.62`.
- Optional LLM judge: provider-neutral, disabled until injected.

## Commands

```bash
.venv/bin/python -m pytest tests/bias_check/ -v
.venv/bin/python -m engines.responsibility.bias_check.evaluate_bias
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m compileall -q .
```

## Verified results

- Bias tests: `58 passed in 4.21s`.
- Full Responsibility Engine: `170 passed in 6.71s`.
- 26-case starter evaluation: precision, recall, and F1 `1.000`; FPR and FNR `0.000` at threshold `0.62`.
- `compileall` and `git diff --check`: passed.

Automated bias detection remains probabilistic and context-dependent. The local tests are ignored by Git as requested.
