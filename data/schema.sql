-- SentinelAI PostgreSQL Schema
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── audit_log ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ  DEFAULT NOW(),
    tenant_id       VARCHAR(100),
    use_case        VARCHAR(50),
    prompt          TEXT,
    llm_response    TEXT,
    final_response  TEXT,
    risk_level      VARCHAR(10),
    risk_score      FLOAT,
    risk_breakdown  JSONB,
    action_taken    VARCHAR(20),
    action_evidence JSONB,
    model_used      VARCHAR(100),
    tokens_used     INT,
    latency_ms      INT,
    flagged_claims  JSONB,
    pii_entities    JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp    ON audit_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_use_case     ON audit_log (use_case);
CREATE INDEX IF NOT EXISTS idx_audit_log_risk_level   ON audit_log (risk_level);
CREATE INDEX IF NOT EXISTS idx_audit_log_action_taken ON audit_log (action_taken);
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_id    ON audit_log (tenant_id);

-- ── feedback ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feedback (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id          UUID        REFERENCES audit_log(id),
    timestamp           TIMESTAMPTZ DEFAULT NOW(),
    sentinelai_action   VARCHAR(20),
    correct_action      VARCHAR(20),
    reviewer_id         VARCHAR(100),
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_feedback_request_id ON feedback (request_id);
CREATE INDEX IF NOT EXISTS idx_feedback_timestamp  ON feedback (timestamp DESC);

-- ── policy_config ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS policy_config (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    use_case         VARCHAR(50) UNIQUE,
    risk_thresholds  JSONB,
    active_checks    JSONB,
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO policy_config (use_case, risk_thresholds, active_checks)
VALUES
    ('customer_chatbot', '{"block_above": 0.75, "escalate_above": 0.60}', '{"pii": true, "bias": true, "groundedness": true}'),
    ('hr_copilot',       '{"block_above": 0.85, "escalate_above": 0.75}', '{"pii": true, "bias": true, "groundedness": true}'),
    ('finance_tool',     '{"block_above": 0.70, "escalate_above": 0.55}', '{"pii": true, "bias": true, "groundedness": true}')
ON CONFLICT (use_case) DO NOTHING;
