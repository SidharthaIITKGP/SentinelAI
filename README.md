# SentinelAI

> **Real-time AI governance control plane.** SentinelAI intercepts LLM requests and responses, evaluates trust, responsibility, and efficiency, and takes governed actions before delivery.

## Problem
As enterprises integrate Large Language Models (LLMs) into production applications (such as HR copilots, customer support chatbots, and internal finance tools), they face significant risks:
- **Trust**: LLMs can hallucinate or provide ungrounded claims.
- **Responsibility**: Users might input prompt injections or toxic content; LLMs might leak PII (Personally Identifiable Information), secrets, or biased content.
- **Efficiency**: Routing every request to the most expensive LLM wastes resources.

## Solution
SentinelAI sits as an interception layer between your application and the LLM. It intercepts incoming prompts, scans them for malicious intent and PII, classifies the risk, dynamically routes the request to the most appropriate model, and evaluates the generated response for groundedness, bias, and data leakage in parallel. Based on a central policy engine, it can **ALLOW**, **REPAIR**, **REDACT**, **BLOCK**, or **ESCALATE** the response before it ever reaches the user.

## Key Features
- **5-Step Governance Pipeline**: Scan -> Classify -> Route & Generate -> Evaluate -> Act & Log.
- **Pre-generation Security**: Real-time prompt injection detection and prompt safety/toxicity checks.
- **Post-generation Guardrails**: Parallel evaluation of groundedness (hallucination detection against a knowledge base), PII detection, and bias detection.
- **Dynamic Model Routing**: Selects the optimal LLM based on preliminary risk classification and use case.
- **Policy Engine**: Centralized decision-making based on risk scores and detected signals.
- **Comprehensive Audit Trail**: Every request, LLM response, evaluated signal, and action taken is logged for compliance.
- **Real-time Dashboard**: A React-based dashboard to visualize intercepted requests, risk scores, and pipeline metrics.

## Architecture

1. **SCAN**: Incoming prompts are scanned for injection attempts and PII. Critical injections or harmful prompts result in an immediate BLOCK.
2. **CLASSIFY**: A preliminary risk level (LOW/MEDIUM/HIGH) is assigned based on the prompt scan and the specific use case.
3. **ROUTE + GENERATE**: The prompt is routed to the appropriate LLM (via LiteLLM) based on the risk level. 
4. **EVALUATE**: The LLM response is evaluated **in parallel** by three engines:
   - **Groundedness Engine**: Verifies claims against a Qdrant vector database.
   - **PII / Secret Detector**: Scans for sensitive information using Microsoft Presidio.
   - **Bias Detector**: Checks for toxicity and endorsed discriminatory bias.
5. **ACT + LOG**: The policy engine determines the final action (e.g., ALLOW, REDACT, BLOCK). The decision and final response are returned, and the entire payload is persisted asynchronously to PostgreSQL.

## Tech Stack
- **Backend**: FastAPI, Python 3, Pydantic
- **Frontend**: React 19, Vite, Tailwind CSS 4, Recharts
- **Databases**: PostgreSQL (Audit Logs), Qdrant (Vector DB for Knowledge Base), Redis (Caching)
- **AI / NLP**: LiteLLM (LLM Routing), Microsoft Presidio (PII Detection), Sentence-Transformers, spaCy

## Project Structure
```text
SentinelAI/
├── api/
│   ├── routes/
│   │   ├── intercept.py      # Core interception endpoint
│   │   ├── responsibility.py # Responsibility & policy endpoints
│   │   └── metrics.py        # Dashboard metrics endpoints
│   └── schemas.py            # Single source of truth for Pydantic data models
├── core/
│   ├── main.py               # FastAPI application entry point
│   ├── pipeline.py           # Central 5-step orchestrator (run_pipeline)
│   ├── action_layer.py       # Governed action execution (ALLOW, BLOCK, REDACT)
│   ├── injection_detector.py # Prompt injection detection
│   └── risk_scorer.py        # Risk score aggregation
├── data/
│   ├── audit_logger.py       # PostgreSQL persistence layer
│   └── schema.sql            # Database schemas
├── engines/
│   ├── trust/                # Groundedness & hallucination checks
│   ├── responsibility/       # PII, bias, and secret detection
│   └── efficiency/           # LLM model routing
├── dashboard/                # React / Vite Frontend
├── policy/                   # OPA / Rego policy engine rules
└── docker-compose.yml        # Infrastructure orchestration
```

## Installation & Setup

### Prerequisites
- Docker and Docker Compose
- Node.js (for local dashboard development)
- Python 3.10+ (for local backend development)

### 1. Clone the repository
```bash
git clone https://github.com/SidharthaIITKGP/SentinelAI
cd SentinelAI
```

### 2. Environment Variables
Create a `.env` file in the root directory based on the `.env.example` format. You will need a Groq API key (or other LLM provider keys supported by LiteLLM).

```env
# .env
GROQ_API_KEY=your_groq_api_key_here
```
*(Never commit your `.env` file to version control.)*

### 3. Running the Project (Docker)
The easiest way to run the complete SentinelAI stack (PostgreSQL, Qdrant, Redis, FastAPI, React Dashboard) is via Docker Compose:

```bash
docker-compose up --build
```

- **API Documentation (Swagger UI)**: http://localhost:8000/docs
- **Dashboard**: http://localhost:5173

## API Usage

The core interaction point for enterprise applications is the `/intercept` endpoint.

### `POST /intercept`
Intercepts an LLM request, runs the governance pipeline, and returns the governed response.

**Request:**
```bash
curl -X POST "http://localhost:8000/intercept" \
     -H "Content-Type: application/json" \
     -d '{
           "prompt": "What is the policy for parental leave?",
           "use_case": "hr_copilot",
           "tenant_id": "acme_corp",
           "user_id": "emp_1042"
         }'
```

**Response:**
```json
{
  "request_id": "e45b21d5-9493-47a3-834c-63b72c918c0c",
  "final_response": "Acme Corp provides 12 weeks of paid parental leave.",
  "action_taken": "ALLOW",
  "risk_level": "LOW",
  "risk_score": 0.2,
  "latency_ms": 842,
  "evidence": {
    "risk_score": 0.2,
    "risk_level": "LOW",
    "policy_reason": "Policy engine stubbed — defaulting to ALLOW"
  },
  "governed": true,
  "escalation_required": false,
  "timestamp": "2026-08-30T11:45:00Z"
}
```

## Security & Guardrails
- **Prompt Injection**: Requests with high-confidence injection patterns are immediately blocked (`ActionType.BLOCK`) without reaching the LLM, returning a safe default message.
- **Harmful Content**: The system evaluates prompts for toxicity and identity hate. Flagged requests are blocked before generation.
- **PII / Secrets**: The responsibility engine scans for SSNs, credit cards, emails, and credentials. If configured, SentinelAI will `REDACT` the sensitive information (e.g., replacing it with `<EMAIL_ADDRESS>`) before returning the payload to the user.
- **Groundedness**: If the LLM generates a claim that completely contradicts the Qdrant knowledge base, the risk score spikes, potentially triggering an `ESCALATE` or `BLOCK` action depending on the policy.

## Audit Logging & Observability
Every intercepted request is fully documented and persisted to PostgreSQL. The `AuditEntry` includes:
- Original prompt and token usage.
- The raw LLM response.
- The final governed response.
- Detailed results from the Injection, PII, Groundedness, and Bias detectors.
- The final policy decision and total latency.

This data feeds directly into the React dashboard for monitoring and compliance review.

## Testing
To run the automated test suite locally (requires the Python environment):

```bash
# Create and activate a virtual environment
python -m venv svenv
source svenv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run pytest
pytest
```

## Technical Highlights
- **Parallel Evaluation**: To minimize latency, Step 4 of the pipeline (EVALUATE) runs the Groundedness, PII, and Bias engines asynchronously in parallel using `asyncio.gather`. 
- **Graceful Degradation**: Engine failures (e.g., a timeout in the Bias detector) are caught, allowing the pipeline to proceed or fallback to safe defaults without crashing the core user experience.
- **Extensible Policy**: The policy engine (designed around OPA) clearly separates the execution of guardrails from the business logic that defines acceptable risk thresholds.

## License
*(Please see the repository for license details, if applicable.)*
