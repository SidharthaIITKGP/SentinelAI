# Gaurav's Implementation Details

This document outlines the changes and additions I made to the `SentinelAI` project, breaking down the specific code I wrote, why I chose certain implementation paths, and how it aligns with the project's goal of being an enterprise-grade AI governance platform.

---

## 1. Database & Persistence Layer

**Files Changed/Added:**
- `data/schema.sql`
- `data/audit_logger.py`

**What I did:**
- Created a robust PostgreSQL schema featuring the `audit_log`, `feedback`, and `policy_config` tables.
- Built `audit_logger.py` using `asyncpg` to asynchronously read from and write to the database. It handles the mapping of Pydantic models (like `AuditEntry`) into flattened JSONB structures appropriate for the SQL schema.

**Why I did it:**
- **Performance:** `asyncpg` was chosen because it is incredibly fast and fits perfectly into a modern, asynchronous FastAPI backend.
- **Traceability:** Enterprise solutions demand full transparency. The `audit_log` table natively captures inputs, outputs, risk levels, detailed JSON risk breakdowns, token usage, and latency for every single request hitting the pipeline.
- **Feedback Loop:** By decoupling the `feedback` table, human reviewers can override the AI's action asynchronously without mutating the original `audit_log` record (which needs to stay immutable for compliance).

---

## 2. Core Engines

**Files Changed/Added:**
- `engines/efficiency/model_router.py`

**What I did:**
- Built the `route_model` logic which takes the `risk_level` and `use_case` to intelligently route the request to either `gpt-4o` or `gpt-4o-mini`. 
- Added an `execute_model` wrapper that utilizes `litellm.acompletion`.

**Why I did it:**
- **Cost vs. Capability:** Running full capabilities on every request is expensive and slow. Low-risk, internal queries (like HR Copilot) are routed to a faster/cheaper model (`gpt-4o-mini`), while customer-facing or high-risk finance queries automatically fall back to the highest quality model (`gpt-4o`).
- **Standardization:** LiteLLM was used because it provides a uniform API. If SentinelAI ever needs to swap from OpenAI to Anthropic or Gemini, the router code barely has to change.

---

## 3. API & Connectivity

**Files Changed/Added:**
- `api/routes/intercept.py`
- `api/routes/metrics.py`

**What I did:**
- Created the main entry point (`POST /intercept`) which receives an `InterceptRequest`, invokes the `core.pipeline.run_pipeline` engine, waits for the result, logs it via the database layer, and returns a structured response to the consumer.
- Built a metrics layer (`GET /metrics` and `GET /audit/recent`) that runs high-level SQL aggregations to calculate average latencies, risk distributions, and action rates.

**Why I did it:**
- **Decoupling:** The API routes cleanly separate the web layer from the core business logic. They do strictly validation and orchestration, relying on the `core` package for heavy lifting.
- **Observability:** Dashboard UIs need fast, aggregated data. The metrics endpoints execute SQL aggregations so the React UI remains lightweight and fast.

---

## 4. The Dashboard (Frontend View)

**Files Changed/Added:**
- Bootstrapped `dashboard/` using Vite + React
- Added Tailwind CSS v4, Recharts, and Lucide Icons
- `dashboard/src/components/*` (`LiveFeed.jsx`, `RiskPanel.jsx`, `PolicyToggle.jsx`, `MetricsPanel.jsx`, `AuditLog.jsx`)
- `dashboard/src/App.jsx` and `dashboard/src/index.css`

**What I did:**
- Created a fully responsive, dark-mode, glassmorphism-styled dashboard. 
- Integrated real-time polling to fetch incoming requests every 3 seconds. 
- Added an interactive "Policy Toggle" tab that allows the judge/user to fire demo payloads to the backend and watch the interceptor catch PII or hallucinations in real time.

**Why I did it:**
- **The "Wow" Factor:** Judges spend 80% of their time looking at the frontend. A generic UI doesn't scream "enterprise governance". I built a dark-slate UI with glowing action tags (emerald/amber/red/purple), smooth slide-out panels, and dynamic donut charts to make the prototype feel premium and expensive.
- **Interactivity:** A static dashboard is boring. The `PolicyToggle` allows you to immediately demonstrate *how* the pipeline reacts differently to a finance query versus an HR query.

---

## 5. Deployment & Containerization

**Files Changed/Added:**
- `docker-compose.yml`
- `Dockerfile.api`
- `dashboard/Dockerfile`
- `requirements.txt`

**What I did:**
- Wrote basic Dockerfiles for the API and frontend, mapping necessary ports (8000 and 5173).
- Defined a `docker-compose.yml` that networks the API, Dashboard, PostgreSQL, Qdrant, and Redis together.
- Connected the DB init script (`schema.sql`) to automatically run when the Postgres container starts for the first time.

**Why I did it:**
- **Zero-Friction Demos:** Complex AI applications with vector databases and relational databases are notoriously hard to set up. `docker-compose` ensures that any judge or team member can run the entire system on their machine via a single command. 
- **Dev-Prod Parity:** Using Docker prevents the "it works on my machine" problem, locking in dependencies (`requirements.txt` and `package.json`).
