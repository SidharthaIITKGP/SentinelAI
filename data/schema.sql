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

-- ── human review queue ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS human_reviews (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id              UUID        NOT NULL UNIQUE REFERENCES audit_log(id),
    tenant_id               VARCHAR(100) NOT NULL,
    use_case                VARCHAR(50)  NOT NULL,
    status                  VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    sentinelai_action       VARCHAR(20)  NOT NULL,
    original_response       TEXT         NOT NULL DEFAULT '',
    holding_response        TEXT         NOT NULL,
    risk_level              VARCHAR(10)  NOT NULL,
    risk_score              FLOAT        NOT NULL,
    action_evidence         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    groundedness_evidence   JSONB,
    efficiency_evidence     JSONB,
    reviewer_id             VARCHAR(100),
    reviewer_notes          TEXT,
    edited_response         TEXT,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    reviewed_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_human_reviews_status     ON human_reviews (status);
CREATE INDEX IF NOT EXISTS idx_human_reviews_created_at ON human_reviews (created_at ASC);
CREATE INDEX IF NOT EXISTS idx_human_reviews_tenant_id  ON human_reviews (tenant_id);
CREATE INDEX IF NOT EXISTS idx_human_reviews_use_case   ON human_reviews (use_case);

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

ALTER TABLE feedback ADD COLUMN IF NOT EXISTS review_id UUID REFERENCES human_reviews(id);
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS false_positive BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS false_negative BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_feedback_request_id ON feedback (request_id);
CREATE INDEX IF NOT EXISTS idx_feedback_timestamp  ON feedback (timestamp DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_review_once
    ON feedback (review_id) WHERE review_id IS NOT NULL;

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
