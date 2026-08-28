# Responsibility Engine

This project protects text before it is sent to an external LLM. The current
intercept flow is simulated: it makes governance decisions but never calls an
LLM or an external verification service.

## Request flow

`POST /responsibility/intercept` accepts text for the `external_llm` target.
It runs the three detectors, combines safe categories and scores, evaluates
the policy, and returns `ALLOW`, `REDACT`, `BLOCK`, or `ESCALATE`. A redacted
prompt is returned only for `REDACT`.

## Main files

- `engines/responsibility/pii_check/pii_detector.py` — Presidio PII detection
  and typed redaction. Supports email, phone, Aadhaar, PAN, and Indian
  passport; results never expose matched values.
- `engines/responsibility/pii_check/secret_detector.py` — local recognition
  and redaction of common credentials, token formats, and cautious
  entropy-plus-context candidates.
- `engines/responsibility/pii_check/confidential_detector.py` — semantic
  classification of confidential business text with `all-MiniLM-L6-v2` and a
  local taxonomy.
- `engines/responsibility/pii_check/config/phase3_taxonomy.json` — local
  aliases, reference phrases, keywords, and negative-context terms used by
  the PII and confidential detectors.
- `engines/responsibility/pii_check/intercept_pipeline.py` — connects the
  existing detectors to policy; aggregates safe evidence without averaging
  away critical signals.
- `engines/responsibility/pii_check/policy/thresholds.yaml` — reviewable
  use-case thresholds and external-target rules.
- `engines/responsibility/pii_check/policy/engine.py` — validates and applies
  the YAML policy rules.
- `api/routes/responsibility.py` — FastAPI endpoints for standalone scans,
  redaction, policy evaluation, and simulated intercept.
- `api/schemas.py` — shared request and response shapes for the API.

## Policy summary

Known credential formats block. Possible high-entropy secrets and confidential
information escalate. PII and generic credentials redact. If no explicit
detector rule applies, per-use-case score thresholds decide between allow,
escalate, and block.

## Running locally

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
uvicorn core.main:app --reload
```

The model download is required once and needs internet access. The tests are
intentionally ignored by Git in this repository, but can be run locally with
`./.venv/bin/python -m pytest -q tests`.
