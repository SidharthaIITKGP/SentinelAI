# api/schemas.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SentinelAI — Single Source of Truth for All Data Shapes
#
# Every other file imports from here. Nobody defines Pydantic models elsewhere.
# This file has ZERO business logic — only data shape definitions.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Section 1 — Enums
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class UseCase(str, Enum):
    """Three valid use cases. Used everywhere — pipeline, policy, risk scorer, audit, dashboard."""
    CUSTOMER_CHATBOT = "customer_chatbot"
    HR_COPILOT = "hr_copilot"
    FINANCE_TOOL = "finance_tool"


class RiskLevel(str, Enum):
    """Three risk tiers output by the risk scorer."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ActionType(str, Enum):
    """Five possible governed actions SentinelAI can take."""
    ALLOW = "ALLOW"
    REPAIR = "REPAIR"
    REDACT = "REDACT"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


class BiasType(str, Enum):
    """Categories of bias the bias detector can identify."""
    GENDER_BIAS = "gender_bias"
    RACIAL_BIAS = "racial_bias"
    AGE_BIAS = "age_bias"
    SOCIOECONOMIC_BIAS = "socioeconomic_bias"
    RELIGIOUS_BIAS = "religious_bias"
    DISABILITY_BIAS = "disability_bias"
    GENERAL_TOXICITY = "general_toxicity"


class PIIEntityType(str, Enum):
    """Types of PII entities Presidio can detect. These are the ones we care about."""
    PERSON = "PERSON"
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    PHONE_NUMBER = "PHONE_NUMBER"
    CREDIT_CARD = "CREDIT_CARD"
    US_SSN = "US_SSN"
    LOCATION = "LOCATION"
    DATE_TIME = "DATE_TIME"
    ORGANIZATION = "ORGANIZATION"
    IBAN_CODE = "IBAN_CODE"
    IP_ADDRESS = "IP_ADDRESS"
    URL = "URL"
    MEDICAL_LICENSE = "MEDICAL_LICENSE"
    NRP = "NRP"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Section 2 — Sub-models (Building Blocks)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PIIEntity(BaseModel):
    """A single piece of PII found in text."""
    model_config = ConfigDict(use_enum_values=True)

    entity_type: PIIEntityType = Field(..., description="What kind of PII (PERSON, EMAIL etc.)")
    text: str = Field(..., description="The actual text that was flagged")
    start: int = Field(..., description="Character position where it starts in the text")
    end: int = Field(..., description="Character position where it ends")
    score: float = Field(..., ge=0.0, le=1.0, description="Presidio's confidence score")
    redacted_placeholder: str = Field(..., description="What it gets replaced with e.g. '<PERSON>'")


class FlaggedClaim(BaseModel):
    """One sentence/claim in an LLM response that couldn't be grounded."""
    model_config = ConfigDict(use_enum_values=True)

    claim_text: str = Field(..., description="The actual sentence that was flagged")
    similarity_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="How close it got to any source (0 = no match, 1 = perfect match)"
    )
    threshold_used: float = Field(
        ..., ge=0.0, le=1.0,
        description="What minimum score was required for this use case"
    )


class SupportingSource(BaseModel):
    """A knowledge base document chunk that DID support part of the response."""
    model_config = ConfigDict(use_enum_values=True)

    doc_id: str = Field(..., description="ID of the source document")
    title: str = Field(..., description="Document title")
    chunk_text: str = Field(..., description="The relevant excerpt")
    similarity_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="How closely it matched the claim"
    )
    use_case: UseCase = Field(..., description="Which use case's knowledge base this came from")


class ModelConfig(BaseModel):
    """What the model router returns — which LLM to use for this request."""
    model_config = ConfigDict(use_enum_values=True)

    model: str = Field(..., description="LiteLLM model string e.g. 'gpt-4o-mini' or 'gpt-4o'")
    max_tokens: int = Field(..., description="Token budget for this request")
    temperature: float = Field(..., ge=0.0, le=1.0, description="0.0 to 1.0, lower = more deterministic")
    reason: str = Field(..., description="Why this model was selected (goes to audit log)")
    estimated_cost_usd: Optional[float] = Field(
        default=None, description="Estimated cost, can be None if unknown"
    )


class PolicyDecision(BaseModel):
    """What OPA policy engine returns after evaluating risk."""
    model_config = ConfigDict(use_enum_values=True)

    approved: bool = Field(..., description="Is the proposed action policy-compliant?")
    final_action: ActionType = Field(
        ..., description="What action OPA says should be taken (may override pipeline's proposal)"
    )
    reason: str = Field(..., description="Why this decision was made (human-readable, goes to audit)")
    policy_file: str = Field(..., description="Which .rego file made this decision")
    threshold_applied: float = Field(
        ..., ge=0.0, le=1.0,
        description="Which threshold triggered this decision"
    )


class RiskBreakdown(BaseModel):
    """Per-signal contribution breakdown inside a RiskScore. Shown as a bar chart on the dashboard."""
    model_config = ConfigDict(use_enum_values=True)

    injection_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="From injection detector"
    )
    pii_prompt_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="PII risk in the incoming prompt"
    )
    pii_response_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="PII risk in the LLM response"
    )
    groundedness_risk: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="INVERTED groundedness: 1 - groundedness_score (high = more hallucination)"
    )
    bias_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="From bias detector"
    )
    dominant_signal: str = Field(
        default="none",
        description="Which signal contributed most (e.g. 'pii_response', 'groundedness_risk')"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Section 3 — Engine Result Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class InjectionResult(BaseModel):
    """Return type of core/injection_detector.py"""
    model_config = ConfigDict(use_enum_values=True)

    detected: bool = Field(..., description="Was an injection attempt found?")
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="How confident is the detector?"
    )
    matched_pattern: Optional[str] = Field(
        default=None, description="The regex pattern that matched, if any"
    )
    method: str = Field(
        default="none",
        description="'pattern_match' | 'embedding_similarity' | 'none'"
    )
    flagged_text: Optional[str] = Field(
        default=None, description="The specific text that triggered detection"
    )

    @model_validator(mode="after")
    def validate_consistency(self):
        """If not detected, confidence should be 0.0 and method should be 'none'."""
        if not self.detected:
            self.confidence = 0.0
            self.method = "none"
        return self


class PIIResult(BaseModel):
    """
    Return type of engines/responsibility/pii_detector.py.
    Called TWICE in the pipeline — once on the prompt, once on the LLM response.
    """
    model_config = ConfigDict(use_enum_values=True)

    found: bool = Field(..., description="Was any PII detected?")
    entities: List[PIIEntity] = Field(
        default_factory=list, description="List of all PII entities found"
    )
    risk_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Overall PII risk severity"
    )
    entity_count: int = Field(default=0, description="Total number of PII entities found")
    high_risk_entities: List[str] = Field(
        default_factory=list,
        description="Entity types considered high risk (SSN, CREDIT_CARD)"
    )
    scan_target: str = Field(
        default="prompt",
        description="'prompt' | 'response' — which text was scanned"
    )

    @model_validator(mode="after")
    def validate_consistency(self):
        """If not found, entities must be empty and risk_score must be 0.0. entity_count must match."""
        if not self.found:
            self.entities = []
            self.risk_score = 0.0
            self.entity_count = 0
        else:
            self.entity_count = len(self.entities)
        return self


class BiasResult(BaseModel):
    """Return type of engines/responsibility/bias_detector.py"""
    model_config = ConfigDict(use_enum_values=True)

    detected: bool = Field(..., description="Was bias found?")
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Severity")
    bias_types: List[BiasType] = Field(
        default_factory=list, description="Which categories were detected"
    )
    flagged_segments: List[str] = Field(
        default_factory=list, description="The actual text snippets that were biased"
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Detector's confidence in its own finding"
    )
    detection_method: str = Field(
        default="pattern_match",
        description="'classifier' | 'pattern_match' | 'both'"
    )

    @model_validator(mode="after")
    def validate_consistency(self):
        """If not detected, bias_types and flagged_segments must be empty."""
        if not self.detected:
            self.bias_types = []
            self.flagged_segments = []
        return self


class GroundednessResult(BaseModel):
    """Return type of engines/trust/groundedness.py"""
    model_config = ConfigDict(use_enum_values=True)

    score: float = Field(
        ..., ge=0.0, le=1.0,
        description="0.0 = complete hallucination, 1.0 = fully grounded"
    )
    flagged_claims: List[FlaggedClaim] = Field(
        default_factory=list,
        description="Claims that couldn't be verified against knowledge base"
    )
    supporting_sources: List[SupportingSource] = Field(
        default_factory=list,
        description="Knowledge base chunks that supported the response"
    )
    total_claims_checked: int = Field(
        default=0, description="How many sentences were evaluated"
    )
    grounded_claims_count: int = Field(
        default=0, description="How many passed the grounding check"
    )
    use_case_kb_used: UseCase = Field(
        ..., description="Which knowledge base was queried"
    )

    @field_validator("grounded_claims_count")
    @classmethod
    def grounded_lte_total(cls, v, info):
        """grounded_claims_count must be <= total_claims_checked."""
        total = info.data.get("total_claims_checked", 0)
        if v > total:
            raise ValueError(
                f"grounded_claims_count ({v}) cannot exceed total_claims_checked ({total})"
            )
        return v


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Section 4 — Core Pipeline Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RiskScore(BaseModel):
    """Output of core/risk_scorer.py. The combined picture from all engines."""
    model_config = ConfigDict(use_enum_values=True)

    overall: float = Field(
        ..., ge=0.0, le=1.0, description="Combined weighted risk score"
    )
    level: RiskLevel = Field(..., description="LOW | MEDIUM | HIGH")
    breakdown: RiskBreakdown = Field(..., description="Per-signal contribution")
    use_case: UseCase = Field(..., description="Which use case's weights were applied")
    computed_at: datetime = Field(
        default_factory=datetime.utcnow, description="When this score was computed"
    )

    @model_validator(mode="after")
    def validate_level_matches_overall(self):
        """Ensure level is consistent with overall score thresholds."""
        if self.overall > 0.65:
            self.level = RiskLevel.HIGH
        elif self.overall > 0.35:
            self.level = RiskLevel.MEDIUM
        else:
            self.level = RiskLevel.LOW
        return self


class ActionResult(BaseModel):
    """Output of core/action_layer.py. The final governed decision."""
    model_config = ConfigDict(use_enum_values=True)

    action: ActionType = Field(..., description="ALLOW | REPAIR | REDACT | BLOCK | ESCALATE")
    final_response: str = Field(..., description="The text that actually goes back to the user")
    original_response: str = Field(..., description="What the LLM originally said")
    evidence: Dict[str, Any] = Field(
        default_factory=dict, description="What triggered this action"
    )
    explanation: str = Field(..., description="Human-readable reason (shown in dashboard)")
    escalation_required: bool = Field(
        default=False, description="True only for ESCALATE action"
    )
    repair_attempted: bool = Field(
        default=False, description="True if REPAIR was tried"
    )
    redacted_entity_count: int = Field(
        default=0, description="How many PII entities were masked (0 if not REDACT)"
    )

    @model_validator(mode="after")
    def validate_action_consistency(self):
        """
        BLOCK → final_response must differ from original_response.
        ALLOW → final_response must equal original_response.
        ESCALATE → escalation_required must be True.
        """
        if self.action == ActionType.BLOCK and self.final_response == self.original_response:
            raise ValueError(
                "BLOCK action must never return the original LLM response"
            )
        if self.action == ActionType.ALLOW and self.final_response != self.original_response:
            raise ValueError(
                "ALLOW action must return the original LLM response unchanged"
            )
        if self.action == ActionType.ESCALATE and not self.escalation_required:
            self.escalation_required = True
        return self


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Section 5 — API Request/Response Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class InterceptRequest(BaseModel):
    """Shape of every incoming API call to POST /intercept."""
    model_config = ConfigDict(use_enum_values=True)

    prompt: str = Field(
        ..., min_length=1, max_length=10000,
        description="The text being sent to the LLM"
    )
    use_case: UseCase = Field(..., description="Which policy config to apply")
    tenant_id: str = Field(
        ..., min_length=1, description="Which company is sending this request"
    )
    user_id: str = Field(
        ..., min_length=1, description="Which user within that company"
    )
    session_id: Optional[str] = Field(
        default=None, description="Conversation session ID for multi-turn tracking"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Any extra context the enterprise app wants to pass"
    )


class InterceptResponse(BaseModel):
    """Shape of what SentinelAI returns to the enterprise app."""
    model_config = ConfigDict(use_enum_values=True)

    request_id: str = Field(..., description="UUID for this request (for tracking/feedback)")
    final_response: str = Field(..., description="The governed response to show the user")
    action_taken: ActionType = Field(..., description="What SentinelAI did")
    risk_level: RiskLevel = Field(..., description="LOW | MEDIUM | HIGH")
    risk_score: float = Field(
        ..., ge=0.0, le=1.0, description="Overall risk score"
    )
    latency_ms: int = Field(..., description="Total pipeline processing time in milliseconds")
    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of what was found and why action was taken"
    )
    governed: bool = Field(
        default=True, description="Always True — signals this response was governed"
    )
    escalation_required: bool = Field(
        default=False, description="True if human review is needed"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the response was generated"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Section 6 — Audit Schema
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AuditEntry(BaseModel):
    """
    The complete record of one pipeline run. Written to PostgreSQL.
    Read back by the dashboard. This is the LARGEST schema.
    """
    model_config = ConfigDict(use_enum_values=True)

    # ── Identity ───────────────────────────────────────────────────────────
    request_id: str = Field(..., description="UUID, primary key")
    timestamp: datetime = Field(..., description="When the request was received")
    tenant_id: str = Field(..., description="Which company")
    user_id: str = Field(..., description="Which user")
    use_case: UseCase = Field(..., description="Which use case config was applied")
    session_id: Optional[str] = Field(
        default=None, description="Conversation session if provided"
    )

    # ── The prompt ─────────────────────────────────────────────────────────
    prompt: str = Field(..., description="Original incoming prompt")
    prompt_length: int = Field(..., description="Character count of prompt")

    # ── LLM interaction ────────────────────────────────────────────────────
    llm_response: str = Field(..., description="Raw LLM output before any SentinelAI action")
    model_used: str = Field(..., description="Which LLM model was called")
    tokens_input: int = Field(..., description="Tokens in the prompt")
    tokens_output: int = Field(..., description="Tokens in the LLM response")
    tokens_total: int = Field(..., description="Sum of input + output")
    estimated_cost_usd: Optional[float] = Field(
        default=None, description="Estimated API cost"
    )

    # ── What was returned ──────────────────────────────────────────────────
    final_response: str = Field(..., description="What was actually returned to the user")

    # ── All engine results (stored as JSONB in PostgreSQL) ─────────────────
    injection: InjectionResult
    pii_in_prompt: PIIResult
    pii_in_response: PIIResult
    groundedness: GroundednessResult
    bias: BiasResult

    # ── Scoring and decision ───────────────────────────────────────────────
    risk_score: RiskScore
    policy_decision: PolicyDecision
    action: ActionResult

    # ── Performance ────────────────────────────────────────────────────────
    latency_ms: int = Field(..., gt=0, description="Total end-to-end pipeline time")
    step_latencies: Dict[str, int] = Field(
        default_factory=dict,
        description='Latency per step e.g. {"scan": 12, "evaluate": 180}'
    )

    # ── Flags ──────────────────────────────────────────────────────────────
    escalation_required: bool = Field(default=False)
    human_reviewed: bool = Field(
        default=False, description="Updated later when a human reviews this entry"
    )
    review_outcome: Optional[str] = Field(
        default=None, description="Filled in after human review"
    )

    @field_validator("tokens_total")
    @classmethod
    def tokens_must_sum(cls, v, info):
        """tokens_total must equal tokens_input + tokens_output."""
        tokens_in = info.data.get("tokens_input", 0)
        tokens_out = info.data.get("tokens_output", 0)
        expected = tokens_in + tokens_out
        if v != expected:
            raise ValueError(
                f"tokens_total ({v}) must equal tokens_input ({tokens_in}) + tokens_output ({tokens_out}) = {expected}"
            )
        return v


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Section 7 — Feedback Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class FeedbackRequest(BaseModel):
    """Shape of POST /feedback — when a human says SentinelAI got it wrong."""
    model_config = ConfigDict(use_enum_values=True)

    request_id: str = Field(
        ..., min_length=1,
        description="UUID of the original request being corrected"
    )
    correct_action: ActionType = Field(
        ..., description="What the human says should have happened"
    )
    sentinelai_action: ActionType = Field(
        ..., description="What SentinelAI actually did"
    )
    reviewer_id: str = Field(
        ..., min_length=1, description="Who is submitting the feedback"
    )
    notes: Optional[str] = Field(
        default=None, description="Free text explanation"
    )
    false_positive: bool = Field(
        default=False,
        description="True if SentinelAI over-flagged (blocked something safe)"
    )
    false_negative: bool = Field(
        default=False,
        description="True if SentinelAI missed something dangerous"
    )

    @model_validator(mode="after")
    def validate_fp_fn_exclusive(self):
        """false_positive and false_negative cannot both be True simultaneously."""
        if self.false_positive and self.false_negative:
            raise ValueError(
                "false_positive and false_negative cannot both be True simultaneously"
            )
        return self


class FeedbackResponse(BaseModel):
    """What POST /feedback returns."""
    model_config = ConfigDict(use_enum_values=True)

    feedback_id: str = Field(..., description="UUID of this feedback record")
    recorded: bool = Field(..., description="Was it successfully saved?")
    message: str = Field(..., description="Confirmation message")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Section 8 — Metrics Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ActionBreakdown(BaseModel):
    """Count of each action type over a time period."""
    model_config = ConfigDict(use_enum_values=True)

    ALLOW: int = 0
    REPAIR: int = 0
    REDACT: int = 0
    BLOCK: int = 0
    ESCALATE: int = 0
    total: int = 0

    @property
    def block_rate(self) -> float:
        """Percentage of requests blocked."""
        return self.BLOCK / self.total if self.total > 0 else 0.0

    @property
    def escalation_rate(self) -> float:
        """Percentage of requests escalated."""
        return self.ESCALATE / self.total if self.total > 0 else 0.0


class RiskDistribution(BaseModel):
    """Count of each risk level over a time period."""
    model_config = ConfigDict(use_enum_values=True)

    LOW: int = 0
    MEDIUM: int = 0
    HIGH: int = 0
    total: int = 0


class UseCaseMetrics(BaseModel):
    """Metrics broken down per use case."""
    model_config = ConfigDict(use_enum_values=True)

    use_case: UseCase
    total_requests: int = 0
    actions: ActionBreakdown = Field(default_factory=ActionBreakdown)
    avg_risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_latency_ms: float = Field(default=0.0, ge=0.0)
    most_common_pii_type: Optional[str] = None
    bias_detection_rate: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Percentage of requests where bias was detected"
    )


class MetricsSummary(BaseModel):
    """
    Full metrics payload returned by GET /metrics.
    Consumed by dashboard MetricsPanel.
    """
    model_config = ConfigDict(use_enum_values=True)

    period: str = Field(..., description="'1h' | '24h' | '7d' | '30d'")
    period_start: datetime
    period_end: datetime
    total_requests: int = 0
    actions: ActionBreakdown = Field(default_factory=ActionBreakdown)
    risk_distribution: RiskDistribution = Field(default_factory=RiskDistribution)
    avg_latency_ms: float = Field(default=0.0, ge=0.0)
    p95_latency_ms: float = Field(
        default=0.0, ge=0.0, description="95th percentile latency"
    )
    false_positive_rate: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="From feedback table: flagged but human said was fine"
    )
    false_negative_rate: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="From feedback table: missed but human said was dangerous"
    )
    by_use_case: List[UseCaseMetrics] = Field(default_factory=list)
    top_pii_types: List[Dict[str, Any]] = Field(
        default_factory=list, description="Most frequently detected PII entity types"
    )
    total_pii_redactions: int = 0
    total_bias_detections: int = 0
    total_hallucinations_caught: int = 0
    estimated_total_cost_usd: float = Field(
        default=0.0, ge=0.0, description="Sum of all LLM costs in the period"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Section 9 — Health Check Schema
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class HealthResponse(BaseModel):
    """Return type of GET /health."""
    model_config = ConfigDict(use_enum_values=True)

    status: str = Field(..., description="'ok' | 'degraded' | 'down'")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    services: Dict[str, bool] = Field(
        default_factory=dict,
        description='{"qdrant": True, "postgres": True, "redis": True, "opa": True}'
    )
    version: str = Field(default="1.0.0", description="App version string")
    uptime_seconds: float = Field(default=0.0, ge=0.0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Verification — All Defined Classes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ALL_SCHEMAS = [
    # Enums
    "UseCase", "RiskLevel", "ActionType", "BiasType", "PIIEntityType",
    # Sub-models
    "PIIEntity", "FlaggedClaim", "SupportingSource", "ModelConfig",
    "PolicyDecision", "RiskBreakdown",
    # Engine Results
    "InjectionResult", "PIIResult", "BiasResult", "GroundednessResult",
    # Core Pipeline
    "RiskScore", "ActionResult",
    # API Request/Response
    "InterceptRequest", "InterceptResponse",
    # Audit
    "AuditEntry",
    # Feedback
    "FeedbackRequest", "FeedbackResponse",
    # Metrics
    "ActionBreakdown", "RiskDistribution", "UseCaseMetrics", "MetricsSummary",
    # Health
    "HealthResponse",
]
