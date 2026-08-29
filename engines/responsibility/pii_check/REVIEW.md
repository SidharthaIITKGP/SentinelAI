# Responsibility Engine Review

## Current Phase

Phase 5 - Simulated No-LLM Intercept Pipeline.

## Goal

Phase 1 delivered Microsoft Presidio PII scanning and anonymization. Phase 2 added local credential detection. Phase 3 adds semantic classification of contextually confidential business information through the planned `all-MiniLM-L6-v2` sentence-transformer model. Phase 4 added a deterministic, versioned policy evaluator. Phase 5 connects the existing detectors to that evaluator in a simulated external-LLM intercept path; it never calls an LLM.

## Existing Architecture

SentinelAI is an early FastAPI project. `api/schemas.py` is the shared source of Pydantic models and defines the responsibility and future pipeline contracts. The responsibility engine, Phase 4 policy evaluator, and a simulated `external_llm` intercept route are available; no real LLM client/provider or response action layer exists yet.

## Files Created

- `engines/responsibility/pii_check/pii_detector.py` — `PresidioPIIDetector` owns Presidio initialization, `scan`, and `anonymize`; it registers custom Indian Aadhaar, PAN, and passport recognizers; `get_pii_detector` lazily creates one process-wide instance.
- `engines/responsibility/pii_check/secret_detector.py` — `SecretDetector` provides local `scan` and `anonymize` operations for known credential formats.
- `engines/responsibility/pii_check/confidential_detector.py` — `ContextualConfidentialDetector` embeds sentence-sized segments and compares them with a local confidential-information reference taxonomy.
- `engines/responsibility/pii_check/REVIEW.md` — this running engineering log.
- `engines/responsibility/pii_check/policy/engine.py` — validates and evaluates the local Phase 4 policy from safe aggregate signals only.
- `engines/responsibility/pii_check/policy/thresholds.yaml` — reviewable per-use-case thresholds and protective actions.
- `engines/responsibility/pii_check/intercept_pipeline.py` — orchestrates existing detector scans, safe evidence aggregation, policy evaluation, and only policy-required redaction.
- `api/routes/responsibility.py` — async `POST /responsibility/scan` and `POST /responsibility/anonymize` for standalone validation.
- `core/main.py` — minimal FastAPI app entry point that mounts the Phase 1 router.
- `requirements.txt` — runtime and test dependencies.
- Package `__init__.py` files under `api`, `api/routes`, `core`, `engines`, and `engines/responsibility`.
- `tests/pii_check/test_pii_detector.py`, `tests/pii_check/test_india_pii.py`, `tests/pii_check/test_secret_detector.py`, `tests/pii_check/test_confidential_detector.py`, `tests/pii_check/test_policy_engine.py`, `tests/pii_check/test_intercept_pipeline.py`, and `tests/pii_check/test_responsibility_api.py` — PII, India-specific PII, credential, semantic-classification, policy, intercept, and API tests.
- `pytest.ini` — makes the repository's top-level packages importable when tests run from `SentinelAI`.

## Files Modified

- `api/schemas.py` — changed `PIIEntity.text` documentation to make it explicitly a safe category placeholder rather than raw PII; added `IN_AADHAAR`, `IN_PAN`, and `IN_PASSPORT` to the shared PII entity enum; added shared PII and Phase 2/3 models. This preserves the project rule that data shapes live only in the shared schemas module and prevents raw sensitive values in API findings.
- `tests/pii_check/test_pii_detector.py` and `tests/pii_check/test_responsibility_api.py` — added synthetic India-specific identifier, checksum rejection, false-positive, mixed-PII, anonymization, and API no-leakage coverage.
- `api/routes/responsibility.py` — added standalone credential scan and anonymization routes without altering the LLM pipeline.
- `api/routes/responsibility.py` — added standalone `POST /responsibility/policy/evaluate` without accepting source text.
- `api/routes/responsibility.py` — added `POST /responsibility/intercept`, which simulates external-LLM governance without calling a model.
- `requirements.txt` — added `sentence-transformers` for the Phase 3 semantic model.
- `api/schemas.py` — added the shared `PolicyEvaluationRequest` schema.
- `api/schemas.py` — added shared simulated-intercept request, response, evidence, and internal safe-policy schemas.
- `requirements.txt` — declares `PyYAML` for the local Phase 4 policy configuration.

## Dependencies Added

- `presidio-analyzer` — Microsoft Presidio's analyzer and built-in recognizers.
- `presidio-anonymizer` — Microsoft Presidio's replacement/redaction engine.
- `spacy` plus the separately installed `en_core_web_sm` model — English NLP support used by Presidio's named-entity recognizers.
- `tldextract` — used by Presidio's built-in email recognizer; configured to use its packaged suffix list with no network request during scans.
- `fastapi` 0.115.x, `uvicorn[standard]`, and `pydantic` — application API runtime. FastAPI is constrained to its established 0.115 release line for compatible test-client behavior.
- `pytest` and `httpx` — automated tests and in-process ASGI endpoint coverage.

Phase 2 introduces no additional package: the detector uses Python's standard-library `re` module. This is intentional for known credential formats, which require exact offsets and deterministic local redaction.

Phase 3 adds `sentence-transformers` (version 3.x) and uses the `all-MiniLM-L6-v2` model. The model is loaded lazily only when a confidential-information endpoint is called; it is not loaded during PII or credential scans.

## Architecture / Request Flow

```
Terminal or API client
  -> /responsibility/scan or /responsibility/anonymize
  -> PresidioPIIDetector
  -> AnalyzerEngine (configured English spaCy NLP + built-in recognizers)
  -> safe PIIResult metadata (offsets, entity category, confidence)
  -> optional AnonymizerEngine typed replacement
  -> API response

Future only: prompt/response -> detector -> policy decision -> LLM/action layer
```

Phase 2 adds this independent flow:

```text
Terminal or API client
  -> /responsibility/secrets/scan or /responsibility/secrets/anonymize
  -> SecretDetector (local token-format patterns)
  -> safe SecretResult metadata (category, offsets, confidence)
  -> optional typed redaction
  -> API response
```

The detector phases do not modify the real LLM request flow. Phase 4 adds policy evaluation only; it does not itself block a live request.

Phase 3 adds this independent flow:

```text
Terminal or API client
  -> /responsibility/confidential/scan or /responsibility/confidential/anonymize
  -> ContextualConfidentialDetector
  -> SentenceTransformer (all-MiniLM-L6-v2)
  -> cosine similarity against local reference phrases
  -> safe category, offsets, confidence, threshold
  -> optional sentence-level typed redaction
```

Phase 4 adds this independent, text-free flow:

```text
safe risk score + PII/secret/confidential booleans + proposed action
  -> /responsibility/policy/evaluate
  -> PolicyEngine + engines/responsibility/pii_check/policy/thresholds.yaml
  -> PolicyDecision (ALLOW, REDACT, ESCALATE, or BLOCK)
```

Precedence is deterministic: block threshold, escalation threshold, PII/secret redaction, confidential-information escalation, then allow. The customer-chatbot thresholds are 0.75/0.60, HR-copilot 0.85/0.75, and finance-tool 0.70/0.55 (block/escalate); equality triggers the threshold action.

There is no real LLM client, provider configuration, response action layer, or OPA runtime in this repository. The simulated route therefore does not claim to govern live LLM traffic or silently substitute an unavailable OPA service.

Phase 5 now adds the simulated intercept flow:

```text
POST /responsibility/intercept {text, scan_target: external_llm}
  -> existing PII, secret, and confidential-information scans (internally as prompt)
  -> safe category/type evidence + non-averaged aggregate risk
  -> PolicyEngine.evaluate_intercept()
  -> ALLOW | REDACT | BLOCK | ESCALATE, plus redacted_prompt only for REDACT
```

The endpoint never calls an LLM or an external verification service. Its evidence contains only booleans, category/type names, a maximum confidence, policy rule IDs, and a generic policy reason; it never returns detector offsets, raw matches, or the source prompt. Detector failures—including unavailable semantic models—produce a generic 503 and do not fall back to an ungoverned decision.

## Presidio Configuration

- `AnalyzerEngine` uses Presidio's `NlpEngineProvider` with spaCy language `en` and model `en_core_web_sm`.
- Presidio's email validation uses `tldextract` configured with its packaged Public Suffix List only and no disk cache, so a scan makes neither an outbound network request nor a cache write.
- `AnonymizerEngine` uses Presidio `replace` operators with category-preserving values such as `<EMAIL_ADDRESS>`.
- The service registers three local custom Presidio `PatternRecognizer` instances before resolving supported entities. It asks Presidio only for entity types that are both in the shared `PIIEntityType` enum and available in its registry, including PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, US_SSN, LOCATION, DATE_TIME, ORGANIZATION, IBAN_CODE, IP_ADDRESS, URL, MEDICAL_LICENSE, NRP, IN_AADHAAR, IN_PAN, and IN_PASSPORT.
- The result contains no raw matched text. Its `text` and `redacted_placeholder` fields both carry placeholders, while `start` and `end` allow downstream handling without retaining the value.
- `IndianAadhaarRecognizer` permits a 12-digit Aadhaar layout beginning with 2–9, with optional spaces/hyphens, and accepts it only when the locally calculated Verhoeff checksum is valid.
- `IndianPanRecognizer` accepts the `AAAAA9999A` structure case-insensitively (normalizing lowercase input for validation) and supplies PAN/income-tax context to Presidio. A valid PAN-shaped value without PAN/tax context remains a low-confidence finding; nearby context raises it to high confidence.
- `IndianPassportRecognizer` accepts the conservative uppercase letter plus seven digits layout only when `passport`, `passport number`, or `travel document` appears nearby. It additionally supplies those context terms to Presidio.
- No external verification API is called. In particular, the detector never calls UIDAI, Income Tax, Passport Seva, or any other remote service.
- When anonymizing overlaps, validated/high-risk identifiers are selected ahead of broad lower-confidence NER spans, preserving typed Indian-identifier placeholders.

## API / Function Contracts

### `PresidioPIIDetector.scan(text, scan_target="prompt") -> PIIResult`

Accepts a string and `prompt` or `response`; returns `found`, safe entity placeholders, offsets, Presidio confidence, risk score, count, and high-risk categories. Empty text is valid and returns no findings. Invalid text/target raises `ValueError`; unavailable Presidio raises `PresidioServiceError`.

### `PresidioPIIDetector.anonymize(text, scan_target="prompt") -> tuple[PIIResult, str]`

Performs a scan then returns its metadata and category-placeholder redacted text. It does not mutate the input.

### `POST /responsibility/scan`

Input: `{"text":"My email is alex@example.com", "scan_target":"prompt"}`. Output includes `contains_pii`, `findings`, `risk_score`, `entity_count`, `high_risk_entities`, and `scan_target`. Missing text and invalid targets return FastAPI validation error 422. Presidio initialization/analysis failures return generic 503 responses, never an internal stack trace.

### `POST /responsibility/anonymize`

Uses the same input and returns the scan fields plus `anonymized_text`, for example `My email is <EMAIL_ADDRESS>`.

### `SecretDetector.scan(text, scan_target="prompt") -> SecretResult`

Accepts a string and `prompt` or `response`. It detects AWS access-key IDs, GitHub tokens, GitLab tokens, OpenAI API keys, Slack tokens, JSON Web Tokens, PEM private-key blocks, and explicitly labelled generic assignments such as `password=...`. It returns only category, offsets, confidence, risk score, count, and high-risk categories; it never returns the credential value. Empty text is valid and returns no findings.

### `SecretDetector.anonymize(text, scan_target="prompt") -> tuple[SecretResult, str]`

Returns safe scan metadata plus text where each credential is replaced with a typed placeholder, such as `<GITHUB_TOKEN>`. It does not mutate the caller's input object.

### `POST /responsibility/secrets/scan`

Input: `{"text":"key=sk-proj-..."}`. Output fields are `contains_secrets`, safe `findings`, `risk_score`, `secret_count`, `high_risk_secret_types`, and `scan_target`. Missing text or invalid targets return 422. An unexpected service error returns a generic 503 without internal details.

### `POST /responsibility/secrets/anonymize`

Uses the same input and returns the secret scan fields plus `anonymized_text`; for example, `aws_access_key=<AWS_ACCESS_KEY_ID>`.

### `ContextualConfidentialDetector.scan(text, scan_target="prompt") -> ConfidentialResult`

Splits text into sentence-sized segments and uses normalized `all-MiniLM-L6-v2` embeddings to compare each segment with local reference phrases. It detects five categories: `INTERNAL_PROJECT`, `FINANCIAL_INFORMATION`, `CUSTOMER_INFORMATION`, `SECURITY_INFORMATION`, and `LEGAL_PRIVILEGED`. It returns only category, offsets, similarity score, threshold, and placeholder. It never returns or logs the source segment.

The current similarity threshold is `0.72`. It is intentionally a detector-local setting in this phase, not a policy-engine decision.

### `ContextualConfidentialDetector.anonymize(text, scan_target="prompt") -> tuple[ConfidentialResult, str]`

Returns safe scan metadata plus text where each flagged sentence segment is replaced with a category-preserving placeholder such as `<CONFIDENTIAL_INFORMATION:FINANCIAL_INFORMATION>`.

### `POST /responsibility/confidential/scan`

Input: `{"text":"The unreleased roadmap defines the launch strategy."}`. Output has `contains_confidential_information`, safe `findings`, `risk_score`, `finding_count`, and `scan_target`. Missing text or malformed targets return 422. An unavailable model or classification failure returns generic 503 without stack traces.

### `POST /responsibility/confidential/anonymize`

Uses the same input and returns scan fields plus `anonymized_text` with category-preserving sentence redaction.

### `PolicyEngine.evaluate(request: PolicyEvaluationRequest) -> PolicyDecision`

Accepts a use case, validated 0–1 risk score, three detector booleans, and an optional proposed action. It returns approval status, the required action, a generic reason, policy filename, and applied threshold. It never accepts, returns, logs, or retains text or raw findings.

### `POST /responsibility/policy/evaluate`

Example: `{"use_case":"finance_tool","risk_score":0.2,"pii_detected":true,"proposed_action":"REDACT"}` returns a safe decision with `final_action: "REDACT"`. Invalid request fields return 422; unavailable or malformed policy configuration returns a generic 503.

### `POST /responsibility/intercept`

Accepts `{"text":"...", "scan_target":"external_llm", "use_case":"customer_chatbot"}`. `external_llm` is deliberately the only public target; internally the unchanged detectors receive their existing `prompt` target. The response has `action_taken`, aggregate `risk_score` and `risk_level`, safe evidence, `governed: true`, and `redacted_prompt` only when the configured action is `REDACT`. Missing text or another target returns 422.

## Testing

From the repository directory:

```bash
cd SentinelAI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
pytest -q tests
uvicorn core.main:app --reload
```

Run only the PII and API coverage, including all India-specific tests:

```bash
pytest -q tests/pii_check/test_pii_detector.py tests/pii_check/test_responsibility_api.py
```

Run the independent India-specific PII suite:

```bash
pytest -q tests/pii_check/test_india_pii.py
```

In a second terminal, activate the same virtual environment and use the curl commands in the project handoff/report.

```bash
# 1. Safe text: contains_pii false, findings empty
curl -X POST http://127.0.0.1:8000/responsibility/scan \
  -H 'Content-Type: application/json' \
  -d '{"text":"Explain how binary search works."}'

# 2. Email: an EMAIL_ADDRESS finding; text is <EMAIL_ADDRESS>, not the email
curl -X POST http://127.0.0.1:8000/responsibility/scan \
  -H 'Content-Type: application/json' \
  -d '{"text":"My email is alex@example.com"}'

# 3. Phone: a PHONE_NUMBER finding (alongside any contextual findings)
curl -X POST http://127.0.0.1:8000/responsibility/scan \
  -H 'Content-Type: application/json' \
  -d '{"text":"Call me on +91 9876543210"}'

# 4. Multiple entities: email and phone are both included in findings
curl -X POST http://127.0.0.1:8000/responsibility/scan \
  -H 'Content-Type: application/json' \
  -d '{"text":"John Smith can be reached at john@example.com or +1 202-555-0198."}'

# 5. Typed anonymization: anonymized_text contains placeholders
curl -X POST http://127.0.0.1:8000/responsibility/anonymize \
  -H 'Content-Type: application/json' \
  -d '{"text":"Contact alex@example.com on +1 202-555-0198"}'

# 6. Credential scan: only metadata is returned, never the key itself
curl -X POST http://127.0.0.1:8000/responsibility/secrets/scan \
  -H 'Content-Type: application/json' \
  -d '{"text":"key=sk-proj-abcdefghijklmnopqrstuvwxyz123456"}'

# 7. Credential anonymization: keeps the key label and masks the value
curl -X POST http://127.0.0.1:8000/responsibility/secrets/anonymize \
  -H 'Content-Type: application/json' \
  -d '{"text":"aws_access_key=AKIAIOSFODNN7EXAMPLE"}'

# 8. Contextual confidential-information scan: response hides the source segment
curl -X POST http://127.0.0.1:8000/responsibility/confidential/scan \
  -H 'Content-Type: application/json' \
  -d '{"text":"The unreleased product roadmap defines our launch strategy."}'

# 9. Contextual confidential-information redaction
curl -X POST http://127.0.0.1:8000/responsibility/confidential/anonymize \
  -H 'Content-Type: application/json' \
  -d '{"text":"The revenue forecast is not public. Explain binary search."}'
```

`contains_pii` says whether any supported recognizer matched; `findings` provides only entity type, offsets, and confidence; `risk_score` is the Phase 1 severity heuristic; `entity_count` is the finding total; `high_risk_entities` lists categories such as credit cards; `scan_target` identifies prompt/response. A typed `<EMAIL_ADDRESS>` or `<PHONE_NUMBER>` replacement proves the real Presidio anonymizer is operating.

## Test Results

Executed from `SentinelAI` after installing dependencies and `en_core_web_sm`:

```text
112 passed in 5.65s
```

The suite covers no PII, email detection, multiple entities, credit-card and IP detection, typed PII anonymization, invalid 16-digit numeric text, empty input, invalid detector target, safe API output, missing text (422), non-string input (422), and malformed `scan_target` (422). The independent India-specific PII suite uses synthetic values only and separates 9 MUST_DETECT cases, 10 MUST_NOT_DETECT cases, and 2 context-dependent/observational cases. It covers checksum-valid Aadhaar with and without spaces, invalid checksums and order numbers, PAN case normalization and invalid shapes, weak versus strong PAN context, passport context/format gating, individual and multi-identifier anonymization, JSON/log text, existing email/phone regressions, safe text, and no raw-value leakage. Phase 2 coverage includes no-secret text, OpenAI key detection without value exposure, multiple secret types, category-preserving anonymization, generic labelled credentials, short/near-match negative cases, specific-token precedence over a generic assignment, quoted-value redaction, empty input, invalid targets, safe API output, and missing credential text (422). Phase 3 coverage injects deterministic vectors which are deliberately independent of the detector's reference wording; it tests safe text, multiple semantic categories, sentence redaction, below-threshold rejection, empty input, invalid targets, safe API output, anonymization, and missing text (422), without requiring a network model download in CI. Phase 4 adds boundary checks for each use case, precedence (block over redaction), protective actions for PII/secrets and confidential signals, malformed-policy rejection, and the HTTP contract. `python -m compileall -q .` also completed successfully.

## Known Limitations

- Named-entity recognition for names, locations, organizations, and dates is model/context dependent and may miss uncommon, ambiguous, non-English, or abbreviated text.
- Pattern recognizers can have false positives/negatives based on formatting and validation context.
- The configured language is English only.
- Aadhaar detection validates only format and the Verhoeff checksum; PAN and passport detection validate only conservative syntax/context. None of these checks prove that an identifier was issued or is active, and no external verification is performed.
- This phase does not decide whether to allow, block, or redact live LLM traffic.
- Secret detection recognizes only documented common token formats and explicitly labelled generic assignments. It is not a complete credential inventory and deliberately does not use entropy scanning yet.
- A correctly formatted example credential will be reported even if it is a test value; the detector cannot verify whether it is live without external service calls, which it does not make.
- Semantic classification is probabilistic. It can miss domain-specific confidential content and can create false positives for text similar to the reference phrases.
- The Phase 3 taxonomy is a small generic starting set; it must be tailored with approved organization-specific examples before production use.
- The model download requires internet access on first use. The service returns 503 if the model/dependency is unavailable instead of falling back silently.

## Phase 3 Hardening Upgrade

### Current Architecture

The existing API routes and detector boundaries are preserved. Phase 3 adds inexpensive local evidence before or alongside the existing models: configured Presidio taxonomy recognizers extend the PII analyzer, secret entropy is evaluated only for secret-context candidates, and confidential classification blends semantic, keyword, rule, and taxonomy evidence. No live-traffic action is taken.

### Files Added

- `engines/responsibility/pii_check/config/phase3_taxonomy.json` — local configurable aliases, domain terms, semantic reference phrases, keywords, and negative-context terms.
- `engines/responsibility/pii_check/phase3_config.py` — one configuration model for taxonomy path, entropy thresholds/allowlist/context, and hybrid semantic weights.
- `tests/pii_check/test_phase3_hardening.py` — independent MUST_DETECT, MUST_NOT_DETECT, and observational Phase 3 acceptance coverage.

### Files Modified

- `engines/responsibility/pii_check/pii_detector.py` — registers taxonomy recognizers for configured people, organizations, projects, and domain terms; safely reports `detection_method` and evidence signals.
- `engines/responsibility/pii_check/secret_detector.py` — adds conservative Shannon-entropy classification for generic credential candidates with secret context.
- `engines/responsibility/pii_check/confidential_detector.py` — replaces semantic-only confidence with configured hybrid evidence scoring.
- `api/schemas.py` — adds additive safe `detection_method` and `signals` fields to PII, secret, and confidential findings, plus `POSSIBLE_SECRET` and domain entity types.

### Stronger NER Design

spaCy model NER remains enabled. A `TaxonomyRecognizer` reads aliases from the local JSON taxonomy rather than detector code. It supports configured people, organizations, projects, and domain terms; aliases return safe `ALIAS` evidence while canonical dictionary entries return `DICTIONARY`. Existing model recognizers return `MODEL_NER`; pattern recognizers return `PATTERN_VALIDATED` unless they supply more specific evidence.

### Pattern / Context Scoring

India-specific Aadhaar remains format + Verhoeff validated. PAN structure is case-normalized and receives confidence `1.0` only near PAN/tax context; a PAN-shaped build identifier remains at most `0.75`. Passport still requires both conservative syntax and nearby passport context. No entropy is used for PII patterns.

### Controlled Entropy Design

Entropy is calculated only after a generic credential pattern finds a value next to secret context. A candidate must meet all of: configured minimum length (16), Shannon entropy threshold (3.5), at least three character classes, nearby secret context, and no configured allowlist/known harmless hash/UUID format. It then returns `POSSIBLE_SECRET` with `ENTROPY_PLUS_CONTEXT`; it is never represented as a confirmed live credential. Known token formats remain `KNOWN_PATTERN_SECRET`.

### Hybrid Semantic Classifier

Configured weights are semantic `0.60`, keywords `0.20`, rules `0.10`, and taxonomy `0.10`; they sum to one and keep embeddings as the primary signal. Negative terms such as `explain`, `generic`, and `template` apply a confidence penalty. Findings return `HYBRID_SEMANTIC` with safe signals such as `semantic_similarity`, `keyword:pricing`, and `taxonomy:Project Orion`.

### Configuration

Set `SENTINELAI_PHASE3_TAXONOMY_PATH` to a local JSON file to replace the default taxonomy. The central model also owns entropy thresholds/context/allowlist and hybrid semantic weights, avoiding scattered detector constants. Configuration is local only; no external source is called.

### Hardening Tests

`tests/pii_check/test_phase3_hardening.py` covers model NER, configured uncommon-person fallback, alias/project taxonomy matches, Apple organization/fruit context, PAN scoring, controlled entropy positives/negatives/allowlist, known JWT behavior, hybrid semantic positives/negative context, mixed PII plus secret scanning, and PII/secret/confidential regressions.

Run it with:

```bash
pytest -q tests/pii_check/test_phase3_hardening.py
```

### Hardening Test Results

```text
22 passed in 5.16s (Phase 3 hardening suite)
112 passed in 5.65s (current full suite)
```

## Phase 4 Policy Evaluation

`engines/responsibility/pii_check/policy/thresholds.yaml` is the single local source for per-use-case policy values. `PolicyEngine` validates the file during construction and fails closed with a generic service error if it is unavailable or malformed. It deliberately accepts only a 0–1 risk score, detector booleans, use case, and proposed action. It cannot leak raw PII, credentials, prompts, or responses because it never receives them.

The same file defines the `external_llm` rules used by the simulated pipeline: known token-format secrets block, entropy-plus-context possible secrets escalate, generic credentials and PII redact, confidential findings escalate, and two independent detector families escalate unless a prior secret rule blocks. Aggregate risk uses the maximum detector risk rather than an average; known high-confidence secrets force `1.0`, and each additional detector family adds the configured `0.10` increment up to `1.0`.

Run Phase 4 coverage with:

```bash
./.venv/bin/python -m pytest -q tests/pii_check/test_policy_engine.py tests/pii_check/test_responsibility_api.py
```

Run simulated intercept coverage with:

```bash
./.venv/bin/python -m pytest -q tests/pii_check/test_intercept_pipeline.py
```

## Next Phase

Replace the simulated endpoint with a real LLM request/response pipeline only after the project adds a provider configuration, a response action layer, auditing, and authenticated tenant handling. Pass safe detector outcomes and the computed score to `PolicyEngine`; do not pass raw PII or secrets into policy reasons or logs.
