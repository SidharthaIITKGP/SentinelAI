# Responsibility Engine Review

This file supplements, and does not replace, the earlier PII/secret/confidential notes in `pii_check/REVIEW.md`.

## Bias Detection Phase

### What was implemented

- A hybrid response-only `BiasDetector` with a protected-dimension taxonomy (gender, race/ethnicity, age, religion, disability, nationality, socioeconomic status, sexual orientation, and marital/family status) and separate behavior taxonomy.
- High-precision configured regular-expression rules for obvious discriminatory assertions.
- A `unitary/toxic-bert` Hugging Face classifier wrapper that exposes toxicity and identity-hate values as separate evidence signals.
- Sentence-embedding semantic matching using `all-MiniLM-L6-v2` and safe reference IDs.
- Context suppression for negation, quoted/reporting, educational, policy, criticism, and anti-discrimination phrasing.
- A non-decisive fairness trigger routes protected-group decision/treatment combinations to semantic analysis and, when enabled, an optional LLM judge.
- A provider-neutral optional LLM judge accepts only strict structured evidence; no external provider is configured by default.
- Non-averaging evidence aggregation: strong explicit or semantic evidence establishes the score floor; additional evidence reinforces it; safe context reduces it. The detector returns evidence and never takes a policy action.
- `PolicyEngine.evaluate()` now accepts `bias_detected`; unless a risk threshold has already applied, a bias signal maps to configured review (`ESCALATE`). The detector itself has no allow/block/escalate logic.
- `POST /responsibility/bias/scan` returns only structured metadata, scores, and safe reference IDs.

### Files created or modified

| File | Purpose |
|---|---|
| `engines/responsibility/bias_check/bias_detector.py` | Runs rule, toxicity, semantic, context, and aggregation checks. |
| `engines/responsibility/bias_check/bias_config.json` | Stores models, patterns, references, and detector thresholds. |
| `engines/responsibility/bias_check/bias_fairness.py` | Routes protected-group decision/treatment language for deeper analysis. |
| `engines/responsibility/bias_check/bias_llm_judge.py` | Validates optional LLM evidence through a provider-neutral interface. |
| `engines/responsibility/bias_check/work.md` | Summarizes the Bias Detection architecture and file purposes. |
| `api/schemas.py` | Defines bias taxonomy, request, evidence, and result models. |
| `api/routes/responsibility.py` | Exposes `POST /responsibility/bias/scan`. |
| `engines/responsibility/pii_check/policy/engine.py` | Sends bias evidence to the policy decision layer. |
| `engines/responsibility/pii_check/policy/thresholds.yaml` | Configures the policy action for detected bias. |
| `requirements.txt` | Adds the Hugging Face classifier dependency. |
| `tests/bias_check/test_bias_detector.py` | Tests detector layers, context, failures, and edge cases. |
| `tests/bias_check/test_bias_api.py` | Tests the bias API and HTTP errors. |
| `tests/bias_check/test_bias_policy.py` | Tests bias policy integration and precedence. |
| `tests/bias_check/test_bias_hybrid_upgrade.py` | Tests fairness routing, subtle bias, safe context, and mocked LLM outcomes. |
| `engines/responsibility/bias_check/bias_validation.json` | Contains deterministic evaluation examples. |
| `engines/responsibility/bias_check/evaluate_bias.py` | Calculates metrics across detector thresholds. |
| `engines/responsibility/review.md` | Records implementation details and verified results. |

### Important architectural decisions

- Toxicity is supporting evidence only: it cannot establish bias risk without rule, semantic, or LLM bias evidence. Non-toxic hiring discrimination can therefore score highly, while toxic language without protected-class bias has bias risk `0.0`.
- Rules are deliberately narrow and high precision; rule matching alone cannot cover paraphrases or subtle preferential treatment.
- Semantic matching was added for paraphrased gender, age, socioeconomic, and religious discrimination. It returns a reference ID rather than private reference wording.
- Quoted, educational, policy, critical, and anti-bias content applies a configurable per-sentence score reduction rather than an unconditional allow. Suppressed evidence retains its raw confidence, adjusted confidence, context modifier, and safe sentence index. Safe context in one sentence therefore cannot hide endorsed bias in another sentence.
- The detector produces evidence and risk only. `PolicyEngine` owns action selection and can combine bias with other signals and use-case thresholds.

### Models and libraries

- `unitary/toxic-bert` via `transformers` text-classification pipeline: toxicity/identity-hate evidence only.
- `all-MiniLM-L6-v2` via `sentence-transformers`: normalized sentence/reference embeddings for semantic bias similarity.
- The process-wide `get_bias_detector()` factory is cached; models and reference embeddings initialize once when the endpoint is first used. Initialization or inference failure raises `BiasDetectorError`; the API returns generic HTTP 503 rather than falsely reporting a safe result.

### Configuration

`engines/responsibility/bias_check/bias_config.json` contains model names, rule/model/semantic/final thresholds, context reduction, toxicity support increment, reinforcement settings, fairness vocabularies, semantic references, context modifiers, and optional LLM settings. The semantic threshold is `0.65`, final threshold is `0.62`, and the LLM judge is disabled unless a provider implementation is injected and enabled. Policy actions remain in `pii_check/policy/thresholds.yaml`.

### Tests added

- Unit coverage defines MUST_DETECT explicit and semantic examples, MUST_NOT_DETECT safe/educational/quoted examples, a CONTEXT_DEPENDENT observational case, all protected dimensions, multiple dimensions, per-sentence context, threshold enforcement, classifier separation, serialization, invalid input/configuration, empty input, and model failure behavior.
- API coverage defines explicit and subtle detection, request validation (422), and unavailable-detector behavior (503).
- Policy tests verify configured bias escalation and risk-threshold precedence.
- After the folder-only reorganization, the project `.venv` reported `58 passed in 4.21s` for `tests/bias_check/` and `170 passed in 6.71s` for the complete suite. Full details are recorded in `bias_check/work.md`.
- The upgrade tests cover all requested MUST_DETECT and MUST_NOT_DETECT cases, low-toxicity bias, high toxicity without bias, fairness-trigger-safe results, mocked LLM biased/safe results, unavailable/missing judges, malformed output, and avoiding unnecessary LLM calls.
- A deterministic evaluation fixture (26 cases) and evaluator were added. It remains a starter fixture, not the requested approximately 240-case validation corpus.

### Evaluation results

The 26-case starter fixture was evaluated with deterministic injected models. At thresholds `0.50`, `0.62`, and `0.75`, it reported precision `1.000`, recall `1.000`, F1 `1.000`, false-positive rate `0.000`, and false-negative rate `0.000`; the script also reports each fixture group separately. The final detector threshold remains `0.62`. A real offline-model smoke matrix detected all five required biased statements and suppressed all six safe/context statements. High toxic-only content returned toxicity `0.9907` but bias risk `0.0`. These are starter results, not production validation.

### Remaining limitations

- The requested full-size validation dataset, per-category evaluation reporting, and calibrated threshold selection remain incomplete.
- Semantic/model behavior is probabilistic, English-focused, and dependent on model availability; it cannot determine objective fairness or fully resolve ambiguous job requirements.
- Context handling is lexical and conservative; complex multi-sentence quotation/endorsement cases need further adversarial evaluation.
- The LLM judge interface and validation are implemented, but no external/local LLM provider client is configured. Enabling it requires an injected implementation and appropriate privacy, timeout, and cost controls.
- The API is independent; bias is not yet included in the simulated intercept pipeline evidence model.

### How to test from the terminal

After installing dependencies into the active environment:

```bash
.venv/bin/python -m pytest tests/bias_check/test_bias_detector.py -v
.venv/bin/python -m pytest tests/bias_check/test_bias_hybrid_upgrade.py -v
.venv/bin/python -m pytest tests/bias_check/test_bias_api.py -v
.venv/bin/python -m pytest tests/bias_check/ -v
.venv/bin/python -m pytest tests/ -v
.venv/bin/python -m engines.responsibility.bias_check.evaluate_bias
.venv/bin/python -m compileall -q .
```

Optional real-model offline smoke test after both models have been cached:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -c 'from engines.responsibility.bias_check.bias_detector import BiasDetector; print(BiasDetector().scan("For leadership roles I would lean toward men because they tend to handle pressure more effectively.").model_dump())'
```

If the `.venv` is activated, the equivalent commands begin with `python -m` as usual.

### Final status

- Complete: detector taxonomy, configured rule/semantic/context/model layers, safe evidence result, policy evaluation integration, endpoint, and deterministic test/evaluation scaffolding.
- Partially complete: evaluation corpus and calibration; the current fixture is intentionally small, although its reported starter-set metrics are recorded above.
- Next phase: expand the independent validation dataset, run and report calibrated per-group metrics, then integrate bias evidence into the full intercept pipeline if that is desired.

### Original Optional LLM Judge Proposal (Superseded)

An LLM judge could be added as a second-pass evidence signal for subtle or missed bias. It should run when the existing score is uncertain **or** when protected-group references appear with decision/comparison language such as `hire`, `select`, `prefer`, `before`, or `over`.

This extra trigger is necessary because a blind spot may produce a very low score rather than an uncertain score. For example, `Beautiful girls should be hired before anyone else` produced `0.0145` because only the low toxicity signal contributed; no explicit or semantic evidence matched.

The LLM should return structured evidence such as protected dimensions, behavior, endorsement, and confidence. It must not decide `ALLOW`, `BLOCK`, or `ESCALATE`; the existing evidence aggregator and `PolicyEngine` should retain those responsibilities. This proposal is now implemented as the provider-neutral interface described below.

### Fairness Trigger and Optional LLM Judge Upgrade

The old detector could produce very low risk for discriminatory wording when toxicity was low and neither a narrow rule nor the semantic candidate regex matched. Toxicity previously established up to `0.55` bias risk by itself, even though it could not identify a protected dimension.

The fairness trigger now looks for all three ingredients: protected-group language, employment/decision language, and preference/comparison/treatment language. A trigger emits safe routing evidence and candidate dimensions only; it never establishes bias. Triggered sentences are sent through dimension-scoped semantic comparison even when the old semantic regex gate does not match.

The optional LLM judge is invoked only for triggered difficult cases: missing bias evidence, uncovered trigger dimensions, rule/semantic disagreement, or ambiguous safe context. Routing is not based only on a score range. Strict `LLMBiasJudgment` validation requires endorsement, dimensions, behaviors, and confidence. Biased LLM evidence can establish risk independently; safe LLM evidence can reduce but cannot erase strong rule evidence. Missing, unavailable, or malformed required judge output raises `BiasDetectorError` rather than returning a false safe result.

Aggregation now starts from the strongest adjusted rule, semantic, or LLM evidence. Multiple independent bias signals reinforce the score. Toxicity/identity-hate can add only a small configured increment after bias evidence exists, so low toxicity never dilutes strong discrimination and high toxicity alone never becomes bias.
