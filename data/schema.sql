-- Every request that passes through SentinelAI
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    tenant_id VARCHAR(100),
    use_case VARCHAR(50),          -- customer_chatbot / hr_copilot / finance_tool
    prompt TEXT,
    llm_response TEXT,
    final_response TEXT,           -- what was actually returned to user
    risk_level VARCHAR(10),        -- LOW / MEDIUM / HIGH
    risk_score FLOAT,              -- 0-1
    risk_breakdown JSONB,          -- {groundedness: 0.3, pii: true, bias: 0.7}
    action_taken VARCHAR(20),      -- ALLOW/REPAIR/REDACT/BLOCK/ESCALATE
    action_evidence JSONB,         -- why this action was taken
    model_used VARCHAR(100),
    tokens_used INT,
    latency_ms INT,
    flagged_claims JSONB,
    pii_entities JSONB
);

-- Human override / feedback
CREATE TABLE feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID REFERENCES audit_log(id),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    sentinelai_action VARCHAR(20),
    correct_action VARCHAR(20),
    reviewer_id VARCHAR(100),
    notes TEXT
);

-- Use case policy configs (what policies are active)
CREATE TABLE policy_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    use_case VARCHAR(50) UNIQUE,
    risk_thresholds JSONB,         -- {block_above: 0.8, escalate_above: 0.6}
    active_checks JSONB,           -- {pii: true, bias: true, groundedness: true}
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
