# AGENT_CONTEXT.md — SentinelAI Coding Agent Handoff
> Read this entire file before writing a single line of code.
> This is your complete context document. Every architecture decision, every file you need to create, every function signature, and every integration point is documented here.

---

## 0. Two-Assistant Workflow (Important)

You are the **coding agent** running in VS Code. Your job is implementation only.

There is a separate **Claude chat session** (claude.ai) that handles all architecture and design decisions. If you encounter a design question that isn't answered in this document, do NOT make assumptions — flag it with a comment `# DESIGN QUESTION: ...` and move on. The human will bring the answer back from the design session.

**Before starting any task:**
1. Re-read this file
2. Check which files already exist in the repo
3. Check which branch you are on — you should be on `sidhartha/core`
4. Never push directly to `main` or `dev`

---

## 1. Project Overview

**Project:** SentinelAI  
**Hackathon:** Accenture Innovation Challenge 2026 — Round 2  
**Track:** Problem Track 1 — ControlPlane.ai  
**Repo:** https://github.com/SidharthaIITKGP/SentinelAI  
**Code deadline:** August 29, 2026

### What We Are Building

SentinelAI is a **real-time AI governance control plane**. It sits inline between an enterprise application and an LLM. Every prompt passes through SentinelAI before reaching the LLM, and every LLM response passes through SentinelAI before reaching the user.

It evaluates requests and responses across 3 dimensions:
- **Trust** — is the response grounded in facts, or is it hallucinating?
- **Responsibility** — does it contain PII, bias, or policy violations?
- **Efficiency** — is the right model being used for this risk level?

Then it takes a governed action: **ALLOW / REPAIR / REDACT / BLOCK / ESCALATE**

Everything is logged to an audit trail. Every decision is explainable.

### The Problem It Solves

Enterprises deploy AI across many use cases simultaneously. AI outputs can be:
- Confidently wrong (hallucinations becoming business decisions)
- Harmful (PII leaking, biased recommendations)
- Wasteful (using expensive models for simple tasks)

These are discovered AFTER the user has already acted on them. SentinelAI catches them in real time, inline, before delivery.

---

## 2. The 5-Step Pipeline (Core Concept)

Every request flows through exactly these 5 steps:

```
STEP 1 — SCAN
  Input: raw prompt from enterprise app
  Actions:
    - Detect prompt injection attempts (injection_detector.py)
    - Detect PII in the prompt (pii_detector.py — Aman's module)
  If critical injection detected → immediately BLOCK, skip all remaining steps

STEP 2 — CLASSIFY
  Input: scan results + use_case
  Actions:
    - Assign risk level: LOW / MEDIUM / HIGH
    - LOW = skip deep evaluation, go straight to LLM
    - MEDIUM = run trust + responsibility checks
    - HIGH = run all checks including bias

STEP 3 — OPTIMIZE + ROUTE
  Input: risk_level + use_case
  Actions:
    - Call model_router.py (Gaurav's module) → get model name + token budget
    - Send prompt to LLM via LiteLLM
    - Receive raw LLM response

STEP 4 — EVALUATE (run all 3 IN PARALLEL using asyncio.gather)
  Input: raw LLM response
  Actions:
    a. groundedness.py → GroundednessResult (hallucination check)
    b. pii_detector.py on RESPONSE → PIIResult (PII in output)
    c. bias_detector.py → BiasResult (Aman's module)
  Then: pass all results to risk_scorer.py → RiskScore

STEP 5 — ACT + LOG
  Input: RiskScore + use_case
  Actions:
    - Call policy engine (Aman's module) → validate proposed action
    - Execute action via action_layer.py
    - Log everything to audit_logger.py (Gaurav's module)
    - Return governed response + decision metadata to caller
```

---

## 3. Three Use Cases (Different Behavior Per Use Case)

SentinelAI is configurable. The same system behaves differently depending on which use case is active. This is the key demo moment.

| Setting | customer_chatbot | hr_copilot | finance_tool |
|---|---|---|---|
| Block threshold | Risk > 0.75 | Risk > 0.85 | Risk > 0.70 |
| Escalate threshold | Risk > 0.60 | Risk > 0.75 | Risk > 0.55 |
| PII redaction | Always | Conditional | Always |
| Bias tolerance | Zero | Low | Zero |
| Groundedness minimum | 0.55 | 0.45 | 0.70 |
| Latency budget | 500ms | 1000ms | 2000ms |

---

## 4. Tech Stack

| Component | Technology |
|---|---|
| Backend framework | FastAPI (async) |
| LLM routing | LiteLLM |
| PII detection | Microsoft Presidio (presidio-analyzer + presidio-anonymizer) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Vector store | Qdrant |
| Policy engine | OPA (Open Policy Agent) via opa-python-client |
| Audit database | PostgreSQL (asyncpg) |
| Caching | Redis |
| Observability | OpenTelemetry |
| Frontend | React + Tailwind CSS + Recharts |
| Containerization | Docker + docker-compose |

---

## 5. Full Repo Structure

```
sentinel-ai/
│
├── README.md
├── docker-compose.yml
├── .env.example
├── requirements.txt
│
├── api/
│   ├── schemas.py                    ← SIDHARTHA — shared Pydantic models, Day 1
│   └── routes/
│       ├── intercept.py              ← GAURAV — POST /intercept endpoint
│       ├── metrics.py                ← GAURAV — GET /metrics endpoint
│       └── feedback.py              ← SIDHARTHA — POST /feedback endpoint
│
├── core/
│   ├── main.py                       ← SIDHARTHA — FastAPI app entry point
│   ├── pipeline.py                   ← SIDHARTHA — 5-step orchestrator
│   ├── risk_scorer.py                ← SIDHARTHA — combines engine signals
│   ├── action_layer.py               ← SIDHARTHA — executes governed action
│   ├── injection_detector.py         ← SIDHARTHA — prompt injection detection
│   └── feedback.py                   ← SIDHARTHA — feedback endpoint logic
│
├── engines/
│   ├── trust/
│   │   ├── groundedness.py           ← SIDHARTHA — hallucination detection
│   │   └── knowledge_base/
│   │       └── sample_docs.json      ← SIDHARTHA — source docs for grounding
│   │
│   ├── responsibility/
│   │   ├── pii_detector.py           ← AMAN — Presidio integration
│   │   └── bias_detector.py          ← AMAN — HuggingFace + pattern matching
│   │
│   └── efficiency/
│       └── model_router.py           ← GAURAV — LiteLLM routing logic
│
├── policy/
│   ├── engine.py                     ← AMAN — OPA integration
│   ├── thresholds.yaml               ← AMAN — risk thresholds per use case
│   └── rules/
│       ├── customer_chatbot.rego     ← AMAN
│       ├── hr_copilot.rego           ← AMAN
│       └── finance_tool.rego         ← AMAN
│
├── data/
│   ├── schema.sql                    ← GAURAV — PostgreSQL schema
│   ├── audit_logger.py               ← GAURAV — async DB read/write
│   └── models.py                     ← GAURAV — SQLAlchemy models
│
├── dashboard/                        ← GAURAV — React frontend
│   └── src/
│       ├── components/
│       │   ├── LiveFeed.jsx
│       │   ├── RiskPanel.jsx
│       │   ├── AuditLog.jsx
│       │   ├── PolicyToggle.jsx
│       │   └── MetricsPanel.jsx
│       └── App.jsx
│
├── tests/
│   └── test_detection.py             ← AMAN — 10+ test cases
│
├── demo/
│   ├── scenarios/
│   │   ├── scenario_1_pii_leak.py    ← SIDHARTHA
│   │   ├── scenario_2_hallucination.py ← SIDHARTHA
│   │   └── scenario_3_bias_block.py  ← SIDHARTHA
│   └── run_demo.py                   ← SIDHARTHA
│
└── docs/
    ├── AGENT_CONTEXT.md              ← this file
    ├── SENTINELAI_TEAM_HANDOFF.md
    └── architecture.md
```

---

## 6. Shared Pydantic Schemas (api/schemas.py)

**This is the FIRST file to create. Everyone imports from here. Do not define data models anywhere else.**

```python
# api/schemas.py

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────────────────

class UseCase(str, Enum):
    CUSTOMER_CHATBOT = "customer_chatbot"
    HR_COPILOT = "hr_copilot"
    FINANCE_TOOL = "finance_tool"

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class ActionType(str, Enum):
    ALLOW = "ALLOW"
    REPAIR = "REPAIR"
    REDACT = "REDACT"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


# ── Request / Response ─────────────────────────────────────────────────────

class InterceptRequest(BaseModel):
    """Shape of every incoming request to SentinelAI's /intercept endpoint"""
    prompt: str = Field(..., description="The text being sent to the LLM")
    use_case: UseCase = Field(..., description="Which policy config to apply")
    tenant_id: str = Field(..., description="Which company is sending this request")
    user_id: str = Field(..., description="Which user within that company")

class InterceptResponse(BaseModel):
    """Shape of what SentinelAI returns to the enterprise app"""
    request_id: str
    final_response: str
    action_taken: ActionType
    risk_level: RiskLevel
    risk_score: float
    latency_ms: int
    evidence: Dict[str, Any]
    governed: bool = True


# ── Engine Results ─────────────────────────────────────────────────────────

class PIIEntity(BaseModel):
    """A single PII entity found in text"""
    entity_type: str        # "PERSON", "EMAIL_ADDRESS", "CREDIT_CARD" etc.
    text: str               # the actual text that was flagged
    start: int              # character position start
    end: int                # character position end
    score: float            # confidence of detection (0-1)

class PIIResult(BaseModel):
    """Return type of pii_detector.py — used for BOTH prompt scan and response scan"""
    found: bool
    entities: List[PIIEntity] = []
    risk_score: float = 0.0     # 0 = no PII, 1 = severe PII leak

class BiasResult(BaseModel):
    """Return type of bias_detector.py"""
    detected: bool
    score: float = 0.0          # 0 = no bias, 1 = severe bias
    bias_types: List[str] = []  # ["gender_bias", "racial_bias", "age_bias"]
    flagged_segments: List[str] = []  # the actual text snippets flagged
    confidence: float = 0.0     # detector's own confidence in its finding

class GroundednessResult(BaseModel):
    """Return type of groundedness.py"""
    score: float                # 0 = completely ungrounded, 1 = fully grounded
    flagged_claims: List[str] = []       # sentences that couldn't be verified
    supporting_sources: List[str] = []   # knowledge base chunks that DID match

class InjectionResult(BaseModel):
    """Return type of injection_detector.py"""
    detected: bool
    confidence: float = 0.0
    matched_pattern: Optional[str] = None
    method: str = "none"        # "pattern_match" | "embedding_similarity" | "none"


# ── Risk Scoring ───────────────────────────────────────────────────────────

class RiskBreakdown(BaseModel):
    """Individual signal contributions to the overall risk score"""
    injection_score: float = 0.0
    pii_prompt_score: float = 0.0
    pii_response_score: float = 0.0
    groundedness_score: float = 0.0     # note: LOW groundedness = HIGH risk
    bias_score: float = 0.0

class RiskScore(BaseModel):
    """Output of risk_scorer.py — the combined picture"""
    overall: float              # 0-1 combined risk score
    level: RiskLevel            # LOW / MEDIUM / HIGH
    breakdown: RiskBreakdown    # per-signal contributions


# ── Action ─────────────────────────────────────────────────────────────────

class ActionResult(BaseModel):
    """Output of action_layer.py — the final governed decision"""
    action: ActionType
    final_response: str         # what actually gets returned to the user
    evidence: Dict[str, Any]    # what triggered this action
    explanation: str            # human-readable reason (shown in dashboard)
    escalation_required: bool = False


# ── Audit ──────────────────────────────────────────────────────────────────

class AuditEntry(BaseModel):
    """Full record of one pipeline run — written to PostgreSQL by audit_logger.py"""
    request_id: str
    timestamp: datetime
    tenant_id: str
    user_id: str
    use_case: UseCase
    prompt: str
    llm_response: str           # raw LLM output before any action
    final_response: str         # what was actually returned to user
    risk_score: RiskScore
    action: ActionResult
    model_used: str
    tokens_used: int
    latency_ms: int
    pii_in_prompt: PIIResult
    pii_in_response: PIIResult
    groundedness: GroundednessResult
    bias: BiasResult
    injection: InjectionResult


# ── Feedback ───────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    """Shape of a human override / correction"""
    request_id: str
    correct_action: ActionType      # what the human says should have happened
    sentinelai_action: ActionType   # what SentinelAI actually did
    reviewer_id: str
    notes: Optional[str] = None

class FeedbackResponse(BaseModel):
    feedback_id: str
    recorded: bool
    message: str


# ── Metrics ────────────────────────────────────────────────────────────────

class ActionBreakdown(BaseModel):
    ALLOW: int = 0
    REPAIR: int = 0
    REDACT: int = 0
    BLOCK: int = 0
    ESCALATE: int = 0

class RiskDistribution(BaseModel):
    LOW: int = 0
    MEDIUM: int = 0
    HIGH: int = 0

class MetricsSummary(BaseModel):
    """Return type of GET /metrics — consumed by dashboard MetricsPanel"""
    period: str
    total_requests: int
    actions: ActionBreakdown
    risk_distribution: RiskDistribution
    avg_latency_ms: float
    false_positive_rate: float
    by_use_case: Dict[str, Dict[str, Any]]
```

---

## 7. File-by-File Build Instructions (Sidhartha's Files)

### 7.1 `core/main.py`

FastAPI application entry point.

**What it does:**
- Creates the FastAPI app instance
- On startup: connects to Qdrant, tests PostgreSQL, initializes Presidio (Aman's module), loads sentence transformer model into memory
- Registers all routers
- Adds CORS middleware so the React dashboard can talk to it
- Exposes `GET /health` → `{"status": "ok", "services": {"qdrant": true, "postgres": true}}`

**Key startup tasks:**
- Initialize Qdrant collection `knowledge_base` if it doesn't exist
- Embed all documents from `engines/trust/knowledge_base/sample_docs.json` and upsert into Qdrant
- Initialize Presidio AnalyzerEngine (slow to start, do it once at startup)
- Load `sentence-transformers/all-MiniLM-L6-v2` model into memory

---

### 7.2 `core/pipeline.py`

**The most important file in the project.** Central 5-step orchestrator.

**Main function signature:**
```python
async def run_pipeline(request: InterceptRequest) -> tuple[ActionResult, AuditEntry]:
```

**Step-by-step logic:**

```
start = time.time()
request_id = str(uuid4())

# STEP 1 — SCAN
injection_result = await injection_detector.scan(request.prompt)
if injection_result.detected and injection_result.confidence > 0.9:
    → immediately return BLOCK action, log to audit, return early

pii_in_prompt = await pii_detector.detect(request.prompt)  # Aman's module

# STEP 2 — CLASSIFY
risk_level = classify_risk(injection_result, pii_in_prompt, request.use_case)
# LOW: no injection, no PII, internal use case
# HIGH: any injection detected, PII in prompt to customer-facing, etc.

# STEP 3 — ROUTE + GENERATE
model_config = model_router.route(risk_level, request.use_case)  # Gaurav's module
llm_response = await call_llm(request.prompt, model_config)

# STEP 4 — EVALUATE (all 3 in parallel)
groundedness_result, pii_response_result, bias_result = await asyncio.gather(
    groundedness.check(llm_response, request.use_case),
    pii_detector.detect(llm_response),   # Aman's module, on RESPONSE this time
    bias_detector.detect(llm_response),  # Aman's module
)

# STEP 5 — SCORE + ACT
risk_score = risk_scorer.compute(
    injection_result, pii_in_prompt, groundedness_result,
    pii_response_result, bias_result, request.use_case
)

policy_decision = await policy_engine.evaluate(risk_score, request.use_case)  # Aman's module
action_result = await action_layer.execute(
    policy_decision, risk_score, llm_response,
    pii_response_result, request.use_case
)

latency_ms = int((time.time() - start) * 1000)

# BUILD AUDIT ENTRY
audit_entry = AuditEntry(
    request_id=request_id,
    timestamp=datetime.utcnow(),
    ... # all fields
)

# LOG (non-blocking)
asyncio.create_task(audit_logger.log(audit_entry))  # Gaurav's module

return action_result, audit_entry
```

---

### 7.3 `core/risk_scorer.py`

**What it does:** Takes all engine outputs, applies use-case-specific weights, returns one `RiskScore`.

**Function signature:**
```python
def compute(
    injection: InjectionResult,
    pii_prompt: PIIResult,
    groundedness: GroundednessResult,
    pii_response: PIIResult,
    bias: BiasResult,
    use_case: UseCase
) -> RiskScore:
```

**Weighting logic:**

```python
# Weights differ by use case
WEIGHTS = {
    UseCase.CUSTOMER_CHATBOT: {
        "injection": 0.30,
        "pii_response": 0.30,   # PII leaking to customer = severe
        "groundedness": 0.20,
        "bias": 0.15,
        "pii_prompt": 0.05,
    },
    UseCase.HR_COPILOT: {
        "injection": 0.20,
        "pii_response": 0.25,
        "groundedness": 0.25,   # factual accuracy matters for HR decisions
        "bias": 0.25,           # bias in HR = legal risk
        "pii_prompt": 0.05,
    },
    UseCase.FINANCE_TOOL: {
        "injection": 0.20,
        "pii_response": 0.20,
        "groundedness": 0.40,   # financial claims MUST be sourced
        "bias": 0.15,
        "pii_prompt": 0.05,
    }
}

# Note: groundedness_score is "how grounded" (high = good)
# Convert to risk contribution: groundedness_risk = 1 - groundedness_score

overall = weighted_sum(all signals with their weights)
level = HIGH if overall > 0.65 else MEDIUM if overall > 0.35 else LOW
```

---

### 7.4 `core/action_layer.py`

**What it does:** Given risk score + policy decision → executes the right action and returns the final response.

**Function signature:**
```python
async def execute(
    policy_decision: PolicyDecision,  # from Aman's OPA engine
    risk_score: RiskScore,
    llm_response: str,
    pii_in_response: PIIResult,
    use_case: UseCase
) -> ActionResult:
```

**Action execution logic:**

```
ALLOW:
  → return llm_response as-is
  → evidence: {"reason": "Risk score below threshold", "score": risk_score.overall}

REPAIR:
  → re-prompt LLM with: "Answer ONLY based on the following verified sources: {top_sources}. Question: {original_prompt}"
  → return repaired response
  → evidence: {"reason": "Hallucination detected", "flagged_claims": [...]}

REDACT:
  → call presidio_anonymizer on llm_response (Aman's module)
  → return redacted text with <ENTITY_TYPE> placeholders
  → evidence: {"reason": "PII detected in response", "entities_redacted": [...]}

BLOCK:
  → return safe fallback message: "I'm unable to provide this information. Please contact support."
  → NEVER return the llm_response
  → evidence: {"reason": "Risk score exceeded block threshold", "score": risk_score.overall}

ESCALATE:
  → return llm_response WITH a human review flag in the response metadata
  → set escalation_required = True in ActionResult
  → evidence: {"reason": "High-risk response requires human review", "use_case": use_case}
```

---

### 7.5 `core/injection_detector.py`

**What it does:** Detects prompt injection attempts in the incoming prompt.

**Function signature:**
```python
async def scan(prompt: str) -> InjectionResult:
```

**Two-layer detection:**

**Layer 1 — Pattern matching (fast, runs first):**
```python
INJECTION_PATTERNS = [
    r"ignore (all |previous |prior )?(instructions|rules|guidelines)",
    r"you are now",
    r"disregard (your|all|previous)",
    r"pretend (you are|to be)",
    r"act as (if you are|a|an)",
    r"forget (everything|all|your instructions)",
    r"your new (instructions|rules|role) are",
    r"system prompt",
    r"jailbreak",
    r"do anything now",
    r"dan mode",
    # add ~10 more common patterns
]
```
If any pattern matches → detected=True, confidence=0.95, method="pattern_match", return immediately

**Layer 2 — Embedding similarity (runs if no pattern match):**
- Embed the incoming prompt using sentence transformer
- Compare cosine similarity against ~20 known injection embeddings stored in Qdrant collection `injection_patterns`
- If max similarity > 0.82 → detected=True, confidence=similarity_score, method="embedding_similarity"

---

### 7.6 `engines/trust/groundedness.py`

**What it does:** Checks if the LLM's response is grounded in the knowledge base. Detects hallucinations.

**Function signatures:**
```python
async def check(response: str, use_case: UseCase) -> GroundednessResult:

async def initialize_knowledge_base(docs_path: str) -> None:
    # Called once at startup from main.py
    # Loads sample_docs.json, embeds each chunk, upserts to Qdrant
```

**Runtime check logic:**
```
1. Split response into individual sentences/claims
2. For each claim:
   a. Embed with sentence transformer
   b. Query Qdrant collection "knowledge_base" for top 3 similar chunks
      (filter by use_case metadata so HR copilot only checks HR docs)
   c. If max similarity < 0.55 → this claim is ungrounded
3. overall_score = grounded_claims / total_claims
4. Return GroundednessResult with score, flagged_claims, supporting_sources
```

---

### 7.7 `engines/trust/knowledge_base/sample_docs.json`

**What it is:** Simulated company knowledge base. 3 sections, one per use case.

**Structure:**
```json
{
  "customer_chatbot": [
    {
      "id": "cc_001",
      "title": "Return Policy",
      "content": "Customers may return any item within 30 days of purchase for a full refund. Items must be in original condition with receipt. Electronics have a 15-day return window."
    },
    {
      "id": "cc_002",
      "title": "Shipping Policy",
      "content": "Standard shipping takes 5-7 business days. Express shipping (2-3 days) is available for $12.99. Free shipping on orders over $50."
    },
    // 8-10 more customer support docs
  ],
  "hr_copilot": [
    {
      "id": "hr_001",
      "title": "Annual Leave Policy",
      "content": "Full-time employees accrue 15 days of annual leave per year. Leave must be approved by direct manager at least 2 weeks in advance."
    },
    // 8-10 more HR policy docs
  ],
  "finance_tool": [
    {
      "id": "fin_001",
      "title": "Q1 2026 Revenue Summary",
      "content": "Total revenue for Q1 2026 was $4.2M, representing 12% growth YoY. North America contributed 68% of total revenue."
    },
    // 8-10 more finance docs
  ]
}
```

Create realistic-sounding but entirely fictional content. Minimum 8 documents per use case.

---

### 7.8 `core/feedback.py`

**What it does:** Handles human override / correction submissions.

**Endpoint:** `POST /feedback`

**Logic:**
```python
async def submit_feedback(feedback: FeedbackRequest) -> FeedbackResponse:
    feedback_id = str(uuid4())
    # Write to feedback table via audit_logger (Gaurav's module)
    await audit_logger.log_feedback(feedback_id, feedback)
    return FeedbackResponse(
        feedback_id=feedback_id,
        recorded=True,
        message="Feedback recorded. This will be used to tune detection thresholds."
    )
```

---

### 7.9 `demo/scenarios/scenario_1_pii_leak.py`

**What it demonstrates:** Customer chatbot receives a prompt that causes the LLM to leak PII in response → SentinelAI REDACTS before delivery.

```python
# Simulates: customer support agent asks about a customer
# LLM responds with full customer details including SSN
# SentinelAI catches it, redacts PII, returns safe response

request = InterceptRequest(
    prompt="Pull up the account details for John Smith who called earlier",
    use_case="customer_chatbot",
    tenant_id="acme_corp",
    user_id="agent_001"
)
# Expected LLM response (simulated): 
#   "John Smith, SSN 123-45-6789, email john.smith@email.com, card ending 4242..."
# Expected SentinelAI action: REDACT
# Expected final response:
#   "<PERSON>, SSN <US_SSN>, email <EMAIL_ADDRESS>, card ending <CREDIT_CARD>..."
```

---

### 7.10 `demo/scenarios/scenario_2_hallucination.py`

**What it demonstrates:** HR copilot invents a company policy that doesn't exist in the handbook → SentinelAI detects low groundedness → REPAIR (re-prompt with actual sources).

```python
request = InterceptRequest(
    prompt="How many sick days am I entitled to per year?",
    use_case="hr_copilot",
    tenant_id="acme_corp",
    user_id="emp_2891"
)
# LLM hallucinates: "You are entitled to 20 sick days per year"
# (actual policy in knowledge base: 10 days)
# Groundedness check: claim not found in HR docs → score 0.28
# Expected action: REPAIR
# Re-prompted response based on actual handbook: "You are entitled to 10 sick days..."
```

---

### 7.11 `demo/scenarios/scenario_3_bias_block.py`

**What it demonstrates:** Finance tool produces a biased investment recommendation → BLOCK + ESCALATE.

```python
request = InterceptRequest(
    prompt="Should we recommend emerging market funds to our senior clients?",
    use_case="finance_tool",
    tenant_id="acme_corp",
    user_id="advisor_042"
)
# LLM responds with age-biased recommendation
# Bias detector fires, score 0.81
# Finance policy: zero bias tolerance
# Expected action: BLOCK + ESCALATE
# Audit log shows: escalation_required=True
```

---

### 7.12 `demo/run_demo.py`

**What it does:** Fires all 3 scenarios in sequence, prints a clean formatted output showing what SentinelAI did for each. This is what plays during the live demo.

```python
# Fires scenario 1, 2, 3 in sequence
# After each: prints
#   ► USE CASE: customer_chatbot
#   ► PROMPT: "Pull up account details for John Smith..."
#   ► LLM RESPONSE: "John Smith, SSN 123-45-6789..."
#   ► RISK SCORE: 0.91 (HIGH)
#   ► ACTION: REDACT
#   ► FINAL RESPONSE: "<PERSON>, SSN <US_SSN>..."
#   ► LATENCY: 287ms
# Then pauses 2 seconds before next scenario
```

---

## 8. External Module Interfaces (What You Import from Teammates)

### From Aman (`engines/responsibility/`)

```python
# pii_detector.py — two functions you call
from engines.responsibility.pii_detector import detect_pii, redact_pii

pii_result: PIIResult = await detect_pii(text="some text")
redacted_text: str = await redact_pii(text="some text with PII")

# bias_detector.py
from engines.responsibility.bias_detector import detect_bias

bias_result: BiasResult = await detect_bias(response="some LLM response")

# policy/engine.py
from policy.engine import evaluate_policy

policy_decision = await evaluate_policy(
    use_case="customer_chatbot",
    risk_score=risk_score,  # RiskScore object
)
# Returns: PolicyDecision(approved=bool, override_action=Optional[ActionType], reason=str)
```

### From Gaurav (`engines/efficiency/` and `data/`)

```python
# model_router.py
from engines.efficiency.model_router import route_model

model_config = route_model(risk_level=RiskLevel.HIGH, use_case=UseCase.CUSTOMER_CHATBOT)
# Returns: ModelConfig(model="gpt-4o", max_tokens=500, temperature=0.3, reason="...")

# audit_logger.py
from data.audit_logger import log_request, log_feedback

await log_request(audit_entry)  # AuditEntry object
await log_feedback(feedback_id, feedback_request)  # FeedbackRequest object
```

---

## 9. Environment Variables (.env.example)

```
# LLM
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here   # fallback model

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinelai

# Redis
REDIS_URL=redis://localhost:6379

# OPA
OPA_URL=http://localhost:8181

# App
APP_ENV=development
LOG_LEVEL=INFO
```

---

## 10. Docker Compose (Gaurav builds this — for reference)

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [postgres, qdrant, redis]

  dashboard:
    build: ./dashboard
    ports: ["3000:3000"]

  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: sentinel
      POSTGRES_PASSWORD: sentinel
      POSTGRES_DB: sentinelai
    ports: ["5432:5432"]

  qdrant:
    image: qdrant/qdrant
    ports: ["6333:6333"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  opa:
    image: openpolicyagent/opa:latest
    ports: ["8181:8181"]
    command: run --server --addr :8181 /policies
    volumes:
      - ./policy/rules:/policies
```

---

## 11. Build Order (Follow This Exactly)

### Day 1 — Foundations
1. Create `api/schemas.py` (full file as specified in Section 6)
2. Create `core/main.py` skeleton (app instance + health check + startup stubs)
3. Create `core/pipeline.py` skeleton (5 steps stubbed with mock returns)
4. Create `core/risk_scorer.py` skeleton
5. Create `core/action_layer.py` skeleton
6. Create `engines/trust/knowledge_base/sample_docs.json` (fictional docs, all 3 use cases)
7. Push `api/schemas.py` to branch immediately — Aman and Gaurav need it

### Day 2 — Core Engines
1. Complete `core/injection_detector.py` fully (pattern matching + Qdrant embedding check)
2. Complete `engines/trust/groundedness.py` fully (embed + Qdrant query + score)
3. Test both in isolation — they have no dependencies on Aman or Gaurav

### Day 3 — Integration
1. Pull Aman's branch: get `pii_detector.py`, `bias_detector.py`, `policy/engine.py`
2. Pull Gaurav's branch: get `model_router.py`, `audit_logger.py`
3. Complete `core/pipeline.py` fully (replace stubs with real module calls)
4. Complete `core/risk_scorer.py` fully
5. Complete `core/action_layer.py` fully
6. Complete `core/feedback.py`
7. Test: fire one request through the full pipeline, verify audit log entry written

### Day 4 — Demo + Polish
1. Write all 3 demo scenarios
2. Write `demo/run_demo.py`
3. Coordinate with Gaurav: connect dashboard to live backend
4. End-to-end test of all 3 demo scenarios
5. Fix integration issues
6. Write README.md

---

## 12. Requirements (requirements.txt)

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
pydantic==2.7.1
python-dotenv==1.0.1
asyncpg==0.29.0
sqlalchemy[asyncio]==2.0.30
redis==5.0.4
qdrant-client==1.9.1
sentence-transformers==2.7.0
litellm==1.40.0
presidio-analyzer==2.2.354
presidio-anonymizer==2.2.354
spacy==3.7.4
transformers==4.41.0
torch==2.3.0
opentelemetry-sdk==1.24.0
opentelemetry-instrumentation-fastapi==0.45b0
opa-python-client==1.3.2
httpx==0.27.0
```

---

## 13. Key Rules

1. **All data models come from `api/schemas.py`** — never define Pydantic models in other files
2. **Pipeline Step 4 must use `asyncio.gather`** — the 3 engines run in parallel, not sequentially
3. **BLOCK action must never return the LLM response** — always return a safe fallback string
4. **Audit logging must be non-blocking** — use `asyncio.create_task()` so it doesn't add to latency
5. **Startup initialization (Qdrant, Presidio, model loading) happens once in `main.py`** — not on every request
6. **Never hardcode API keys** — always read from environment variables
7. **Branch:** always work on `sidhartha/core`, never push to `main` directly

---

## 14. Design Questions (Flag These, Don't Assume)

If you encounter questions about:
- Which OPA policy field names Aman is using
- Exact DB column names from Gaurav's schema
- Whether to use sync or async for a specific Aman/Gaurav function

Add a comment `# DESIGN QUESTION: <your question>` and continue with a reasonable stub. The human will resolve it in the next session.

---

*This document was generated from architecture sessions. Last updated: August 26, 2026.*
*For design questions, refer to the Claude.ai project conversation.*
```
