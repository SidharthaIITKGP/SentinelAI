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


class DetectorStatus(str, Enum):
    """Whether a detector produced an actual result for this request."""
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class GroundednessVerdict(str, Enum):
    """Evidence outcome, distinct from whether the detector was operational."""
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNAVAILABLE = "UNAVAILABLE"


class ModelTier(str, Enum):
    """Logical model tiers used by the deterministic efficiency router."""
    ECONOMY = "ECONOMY"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ComplexityLevel(str, Enum):
    """Explainable prompt-complexity bands; no LLM classification is used."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class BiasType(str, Enum):
    """Categories of bias the bias detector can identify."""
    GENDER_BIAS = "gender_bias"
    RACIAL_BIAS = "racial_bias"
    AGE_BIAS = "age_bias"
    SOCIOECONOMIC_BIAS = "socioeconomic_bias"
    RELIGIOUS_BIAS = "religious_bias"
    DISABILITY_BIAS = "disability_bias"
    GENERAL_TOXICITY = "general_toxicity"


class ProtectedDimension(str, Enum):
    """Protected demographic dimensions for bias detection."""
    GENDER = "GENDER"
    RACE_ETHNICITY = "RACE_ETHNICITY"
    AGE = "AGE"
    RELIGION = "RELIGION"
    DISABILITY = "DISABILITY"
    NATIONALITY = "NATIONALITY"
    SOCIOECONOMIC_STATUS = "SOCIOECONOMIC_STATUS"
    SEXUAL_ORIENTATION = "SEXUAL_ORIENTATION"
    MARITAL_FAMILY_STATUS = "MARITAL_FAMILY_STATUS"


class BiasBehavior(str, Enum):
    """Types of biased behavior the bias detector can identify."""
    STEREOTYPING = "STEREOTYPING"
    DIFFERENTIAL_TREATMENT = "DIFFERENTIAL_TREATMENT"
    EXCLUSION = "EXCLUSION"
    DEMOGRAPHIC_ASSUMPTION = "DEMOGRAPHIC_ASSUMPTION"
    DEROGATORY_GENERALIZATION = "DEROGATORY_GENERALIZATION"


class LLMBiasJudgment(BaseModel):
    """Strict evidence-only contract returned by an optional LLM bias judge."""
    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    endorses_bias: bool
    protected_dimensions: List[ProtectedDimension] = Field(default_factory=list)
    behaviors: List[BiasBehavior] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_bias_evidence(self):
        if self.endorses_bias and not self.protected_dimensions:
            raise ValueError("endorsed bias requires a protected dimension")
        if self.endorses_bias and not self.behaviors:
            raise ValueError("endorsed bias requires a behavior")
        if not self.endorses_bias:
            self.protected_dimensions = []
            self.behaviors = []
        return self


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
    IN_AADHAAR = "IN_AADHAAR"
    IN_PAN = "IN_PAN"
    IN_PASSPORT = "IN_PASSPORT"
    DOMAIN_ORGANIZATION = "DOMAIN_ORGANIZATION"
    DOMAIN_PROJECT = "DOMAIN_PROJECT"
    DOMAIN_TERM = "DOMAIN_TERM"


class SecretType(str, Enum):
    """Credential categories recognized by the Phase 2 secret detector."""
    AWS_ACCESS_KEY_ID = "AWS_ACCESS_KEY_ID"
    GITHUB_TOKEN = "GITHUB_TOKEN"
    GITLAB_TOKEN = "GITLAB_TOKEN"
    OPENAI_API_KEY = "OPENAI_API_KEY"
    SLACK_TOKEN = "SLACK_TOKEN"
    JSON_WEB_TOKEN = "JSON_WEB_TOKEN"
    PRIVATE_KEY = "PRIVATE_KEY"
    GENERIC_CREDENTIAL = "GENERIC_CREDENTIAL"
    POSSIBLE_SECRET = "POSSIBLE_SECRET"


class ConfidentialCategory(str, Enum):
    """Contextual business-information categories detected in Phase 3."""
    INTERNAL_PROJECT = "INTERNAL_PROJECT"
    FINANCIAL_INFORMATION = "FINANCIAL_INFORMATION"
    CUSTOMER_INFORMATION = "CUSTOMER_INFORMATION"
    SECURITY_INFORMATION = "SECURITY_INFORMATION"
    LEGAL_PRIVILEGED = "LEGAL_PRIVILEGED"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Section 2 — Sub-models (Building Blocks)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PIIEntity(BaseModel):
    """Safe metadata for one PII finding; raw detected values are never returned."""
    model_config = ConfigDict(use_enum_values=True)

    entity_type: PIIEntityType = Field(..., description="What kind of PII (PERSON, EMAIL etc.)")
    text: str = Field(..., description="Safe category placeholder, never the detected value")
    start: int = Field(..., description="Character position where it starts in the text")
    end: int = Field(..., description="Character position where it ends")
    score: float = Field(..., ge=0.0, le=1.0, description="Presidio's confidence score")
    redacted_placeholder: str = Field(..., description="What it gets replaced with e.g. '<PERSON>'")
    detection_method: str = Field(
        default="PATTERN_VALIDATED",
        description="How this entity was detected: MODEL_NER | PATTERN_VALIDATED | DICTIONARY | ALIAS"
    )
    signals: List[str] = Field(
        default_factory=list,
        description="Additional detection signals"
    )


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


class ClaimEvaluation(BaseModel):
    """Deterministic evidence evaluation for one material response claim."""
    model_config = ConfigDict(use_enum_values=True)

    claim_text: str
    verdict: GroundednessVerdict
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    source_doc_id: Optional[str] = None
    source_title: Optional[str] = None
    source_excerpt: Optional[str] = None
    reason: str
    contradiction_type: Optional[str] = None


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


class ModelProfile(BaseModel):
    """One enabled or disabled model profile loaded from the local registry."""
    model_config = ConfigDict(use_enum_values=True)

    id: str
    provider_model: str
    tier: ModelTier
    capability_score: float = Field(..., ge=0.0, le=1.0)
    input_cost_per_1m_tokens: float = Field(..., ge=0.0)
    output_cost_per_1m_tokens: float = Field(..., ge=0.0)
    expected_latency_ms: int = Field(..., gt=0)
    context_window: int = Field(..., gt=0)
    max_output_tokens: int = Field(..., gt=0)
    supported_use_cases: List[UseCase]
    supported_risk_levels: List[RiskLevel]
    enabled: bool = True
    estimated_profile: bool = True


class ComplexityAssessment(BaseModel):
    """Deterministic prompt complexity with inspectable contributing reasons."""
    model_config = ConfigDict(use_enum_values=True)

    level: ComplexityLevel
    score: int = Field(..., ge=0)
    estimated_input_tokens: int = Field(..., ge=0)
    reasons: List[str] = Field(default_factory=list)


class RoutingResult(ModelConfig):
    """Complete model selection, constraint, cost, and latency explanation."""
    model_config = ConfigDict(use_enum_values=True)

    selected_model: str
    selected_profile_id: str
    selected_tier: ModelTier
    baseline_model: str
    baseline_profile_id: str
    routing_reason: str
    complexity: ComplexityAssessment
    estimated_input_tokens: int = Field(..., ge=0)
    estimated_output_tokens: int = Field(..., ge=0)
    baseline_estimated_cost_usd: float = Field(..., ge=0.0)
    estimated_savings_usd: float
    estimated_savings_percent: float
    expected_latency_ms: int = Field(..., gt=0)
    latency_budget_ms: int = Field(..., gt=0)
    latency_budget_breached: bool
    capability_required: float = Field(..., ge=0.0, le=1.0)
    capability_selected: float = Field(..., ge=0.0, le=1.0)
    capability_requirement_met: bool
    context_window_sufficient: bool
    constraints_unmet: List[str] = Field(default_factory=list)
    profile_values_are_estimated: bool = True

    @model_validator(mode="after")
    def selected_model_matches_generation_model(self):
        if self.model != self.selected_model:
            raise ValueError("model must match selected_model")
        return self


class EfficiencyResult(BaseModel):
    """Cost, latency, and capability balance for the selected route."""
    model_config = ConfigDict(use_enum_values=True)

    model_fit_score: float = Field(..., ge=0.0, le=1.0)
    cost_score: float = Field(..., ge=0.0, le=1.0)
    latency_score: float = Field(..., ge=0.0, le=1.0)
    overall_efficiency_score: float = Field(..., ge=0.0, le=1.0)
    selected_model: str
    selected_tier: ModelTier
    baseline_model: str
    estimated_cost_usd: float = Field(..., ge=0.0)
    baseline_estimated_cost_usd: float = Field(..., ge=0.0)
    estimated_savings_usd: float
    estimated_savings_percent: float
    expected_latency_ms: int = Field(..., gt=0)
    actual_latency_ms: Optional[int] = Field(default=None, ge=0)
    latency_budget_ms: int = Field(..., gt=0)
    latency_budget_breached: bool
    capability_required: float = Field(..., ge=0.0, le=1.0)
    capability_selected: float = Field(..., ge=0.0, le=1.0)
    capability_requirement_met: bool
    retry_count: int = Field(default=0, ge=0)
    explanation: List[str] = Field(default_factory=list)
    values_are_estimated: bool = True


class PolicyDecision(BaseModel):
    """Policy-engine decision after evaluating safe risk and detector signals."""
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
    policy_rule_ids: List[str] = Field(
        default_factory=list,
        description="Which policy rules triggered this decision"
    )


class PolicyEvaluationRequest(BaseModel):
    """Input to the policy engine for response-side evaluation."""
    model_config = ConfigDict(use_enum_values=True)

    use_case: UseCase
    risk_score: float = Field(..., ge=0.0, le=1.0)
    proposed_action: ActionType = Field(default=ActionType.ALLOW)
    pii_detected: bool = Field(default=False)
    bias_detected: bool = Field(default=False)
    secrets_detected: bool = Field(default=False)
    confidential_detected: bool = Field(default=False)


class InterceptPolicyRequest(BaseModel):
    """Input to the policy engine for prompt-side intercept evaluation."""
    model_config = ConfigDict(use_enum_values=True)

    use_case: UseCase
    scan_target: str = Field(default="external_llm")
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    proposed_action: ActionType = Field(default=ActionType.ALLOW)
    pii_detected: bool = Field(default=False)
    known_high_confidence_secret: bool = Field(default=False)
    possible_secret: bool = Field(default=False)
    secret_detected: bool = Field(default=False)
    confidential_detected: bool = Field(default=False)
    signal_count: int = Field(default=0)


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
    status: DetectorStatus = Field(
        default=DetectorStatus.AVAILABLE,
        description="AVAILABLE when the detector ran; UNAVAILABLE on detector failure",
    )
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
    Return type of engines/responsibility/pii_check/pii_detector.py.
    Called TWICE in the pipeline — once on the prompt, once on the LLM response.
    """
    model_config = ConfigDict(use_enum_values=True)

    found: bool = Field(..., description="Was any PII detected?")
    status: DetectorStatus = Field(
        default=DetectorStatus.AVAILABLE,
        description="AVAILABLE when the detector ran; UNAVAILABLE on detector failure",
    )
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


class PiiTextRequest(BaseModel):
    """Independent Responsibility Engine request for a text scan or redaction."""
    text: str = Field(..., description="Text to inspect; the service does not log it")
    scan_target: str = Field(default="prompt", pattern="^(prompt|response)$")


class PiiScanResponse(BaseModel):
    """Safe scan response with offsets and entity categories only."""
    contains_pii: bool
    findings: List[PIIEntity] = Field(default_factory=list)
    risk_score: float = Field(ge=0.0, le=1.0)
    entity_count: int = Field(ge=0)
    high_risk_entities: List[str] = Field(default_factory=list)
    scan_target: str


class PiiAnonymizeResponse(PiiScanResponse):
    """Scan response plus typed-placeholder redacted text."""
    anonymized_text: str


class SecretFinding(BaseModel):
    """Safe credential metadata; credential values are never returned."""
    model_config = ConfigDict(use_enum_values=True)
    secret_type: SecretType
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    score: float = Field(..., ge=0.0, le=1.0)
    redacted_placeholder: str
    detection_method: str = Field(default="KNOWN_PATTERN_SECRET")
    signals: List[str] = Field(default_factory=list)


class SecretResult(BaseModel):
    """Return type of engines/responsibility/pii_check/secret_detector.py."""
    model_config = ConfigDict(use_enum_values=True)
    found: bool
    findings: List[SecretFinding] = Field(default_factory=list)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    secret_count: int = Field(default=0, ge=0)
    high_risk_secret_types: List[str] = Field(default_factory=list)
    scan_target: str = Field(default="prompt", pattern="^(prompt|response)$")

    @model_validator(mode="after")
    def validate_consistency(self):
        if not self.found:
            self.findings, self.risk_score, self.secret_count = [], 0.0, 0
            self.high_risk_secret_types = []
        else:
            self.secret_count = len(self.findings)
        return self


class SecretTextRequest(BaseModel):
    """Independent Responsibility Engine request for secret detection/redaction."""
    text: str = Field(..., description="Text to inspect; the service does not log it")
    scan_target: str = Field(default="prompt", pattern="^(prompt|response)$")


class SecretScanResponse(BaseModel):
    """Safe credential scan response with metadata but no credential values."""
    contains_secrets: bool
    findings: List[SecretFinding] = Field(default_factory=list)
    risk_score: float = Field(ge=0.0, le=1.0)
    secret_count: int = Field(ge=0)
    high_risk_secret_types: List[str] = Field(default_factory=list)
    scan_target: str


class SecretAnonymizeResponse(SecretScanResponse):
    anonymized_text: str


class ConfidentialFinding(BaseModel):
    """Safe metadata for a contextually confidential text segment."""
    model_config = ConfigDict(use_enum_values=True)
    category: ConfidentialCategory
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    score: float = Field(..., ge=0.0, le=1.0)
    threshold: float = Field(..., ge=0.0, le=1.0)
    redacted_placeholder: str
    detection_method: str = Field(default="HYBRID_SEMANTIC")
    signals: List[str] = Field(default_factory=list)


class ConfidentialResult(BaseModel):
    """Return type of engines/responsibility/pii_check/confidential_detector.py."""
    model_config = ConfigDict(use_enum_values=True)
    detected: bool
    findings: List[ConfidentialFinding] = Field(default_factory=list)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    finding_count: int = Field(default=0, ge=0)
    scan_target: str = Field(default="prompt", pattern="^(prompt|response)$")

    @model_validator(mode="after")
    def validate_consistency(self):
        if not self.detected:
            self.findings, self.risk_score, self.finding_count = [], 0.0, 0
        else:
            self.finding_count = len(self.findings)
        return self


class ConfidentialTextRequest(BaseModel):
    """Independent Responsibility Engine request for contextual classification."""
    text: str = Field(..., description="Text to inspect; the service does not log it")
    scan_target: str = Field(default="prompt", pattern="^(prompt|response)$")


class ConfidentialScanResponse(BaseModel):
    """Safe semantic-classification response with no raw confidential text."""
    contains_confidential_information: bool
    findings: List[ConfidentialFinding] = Field(default_factory=list)
    risk_score: float = Field(ge=0.0, le=1.0)
    finding_count: int = Field(ge=0)
    scan_target: str


class ConfidentialAnonymizeResponse(ConfidentialScanResponse):
    anonymized_text: str


class SimulatedInterceptRequest(BaseModel):
    """No-LLM integration request for governing text sent to an external model."""
    model_config = ConfigDict(use_enum_values=True)

    text: str = Field(..., min_length=1, max_length=10000, description="Text to govern; never logged")
    scan_target: str = Field(default="external_llm", pattern="^external_llm$")
    use_case: UseCase = UseCase.CUSTOMER_CHATBOT


class InterceptEvidence(BaseModel):
    """Safe aggregate evidence; source text and sensitive values are excluded."""
    pii_detected: bool
    secret_detected: bool
    confidential_detected: bool
    pii_types: List[str] = Field(default_factory=list)
    secret_types: List[str] = Field(default_factory=list)
    confidential_categories: List[str] = Field(default_factory=list)
    max_confidence: float = Field(ge=0.0, le=1.0)
    policy_rule_ids: List[str] = Field(default_factory=list)
    policy_reason: str


class SimulatedInterceptResponse(BaseModel):
    """Safe governance outcome from the simulated no-LLM intercept pipeline."""
    model_config = ConfigDict(use_enum_values=True)

    action_taken: ActionType
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    evidence: InterceptEvidence
    governed: bool = True
    redacted_prompt: Optional[str] = None


class BiasResult(BaseModel):
    """Return type of engines/responsibility/bias_check/bias_detector.py"""
    model_config = ConfigDict(use_enum_values=True)

    detected: bool = Field(..., description="Was bias found?")
    status: DetectorStatus = Field(
        default=DetectorStatus.AVAILABLE,
        description="AVAILABLE when the detector ran; UNAVAILABLE on detector failure",
    )
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Deprecated alias for risk_score")
    detection_method: str = Field(
        default="pattern_match",
        description="'classifier' | 'pattern_match' | 'both'"
    )
    protected_dimensions: List[ProtectedDimension] = Field(
        default_factory=list,
        description="Protected demographic dimensions where bias was detected"
    )
    behaviors: List[BiasBehavior] = Field(
        default_factory=list,
        description="Types of biased behaviors detected"
    )
    evidence: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed evidence from each detection layer"
    )
    toxicity_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Raw toxicity classifier score"
    )
    identity_hate_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Raw identity hate classifier score"
    )
    risk_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Aggregated risk score from all bias signals"
    )
    bias_types: List[BiasType] = Field(
        default_factory=list,
        description="Which categories were detected"
    )
    flagged_segments: List[str] = Field(
        default_factory=list,
        description="The actual text snippets that were biased"
    )

    @model_validator(mode="after")
    def validate_consistency(self):
        """Keep observational signals even when they do not cross the verdict threshold."""
        if not self.detected:
            self.bias_types = []
            self.flagged_segments = []
        return self


class BiasTextRequest(BaseModel):
    """Text from an LLM response to inspect for biased assertions."""
    text: str = Field(..., min_length=1, max_length=10000)
    scan_target: str = Field(default="response", pattern="^response$")


class BiasScanResponse(BaseModel):
    detected: bool
    risk_score: float = Field(ge=0.0, le=1.0)
    protected_dimensions: List[ProtectedDimension] = Field(default_factory=list)
    behaviors: List[BiasBehavior] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    toxicity_score: float = Field(ge=0.0, le=1.0)
    identity_hate_score: float = Field(ge=0.0, le=1.0)
    detection_method: str
    scan_target: str


class GroundednessResult(BaseModel):
    """Return type of engines/trust/groundedness.py"""
    model_config = ConfigDict(use_enum_values=True)

    status: DetectorStatus = Field(
        default=DetectorStatus.AVAILABLE,
        description="AVAILABLE when verification ran; UNAVAILABLE when it could not run",
    )
    verdict: GroundednessVerdict = Field(
        default=GroundednessVerdict.SUPPORTED,
        description="SUPPORTED, CONTRADICTED, INSUFFICIENT_EVIDENCE, or UNAVAILABLE",
    )

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
    claim_evaluations: List[ClaimEvaluation] = Field(
        default_factory=list,
        description="Per-claim deterministic verdicts and evidence references",
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

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_unavailable_construction(cls, data):
        """Infer the new verdict/status pair when legacy callers provide only one."""
        if isinstance(data, dict):
            normalized = dict(data)
            if "verdict" not in normalized and normalized.get("status") in {
                DetectorStatus.UNAVAILABLE,
                DetectorStatus.UNAVAILABLE.value,
            }:
                normalized["verdict"] = GroundednessVerdict.UNAVAILABLE
            if "status" not in normalized and normalized.get("verdict") in {
                GroundednessVerdict.UNAVAILABLE,
                GroundednessVerdict.UNAVAILABLE.value,
            }:
                normalized["status"] = DetectorStatus.UNAVAILABLE
            return normalized
        return data

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

    @model_validator(mode="after")
    def unavailable_is_not_verified(self):
        """Unavailable verification must never serialize as fully grounded."""
        is_unavailable = self.status == DetectorStatus.UNAVAILABLE
        verdict_unavailable = self.verdict == GroundednessVerdict.UNAVAILABLE
        if is_unavailable != verdict_unavailable:
            raise ValueError(
                "groundedness status is UNAVAILABLE iff verdict is UNAVAILABLE"
            )
        if is_unavailable:
            if self.score != 0.0:
                raise ValueError("UNAVAILABLE groundedness must use score 0.0")
            self.total_claims_checked = 0
            self.grounded_claims_count = 0
            self.flagged_claims = []
            self.supporting_sources = []
            self.claim_evaluations = []
        return self


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
        """Reject inconsistent levels; never silently apply another threshold rule."""
        from core.risk_thresholds import risk_level_value

        expected = risk_level_value(self.overall)
        if self.level != expected:
            raise ValueError(
                f"risk level {self.level} does not match score {self.overall}; "
                f"expected {expected}"
            )
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
    repair_attempts: int = Field(
        default=0, ge=0, le=1, description="Bounded repair call count"
    )
    redacted_entity_count: int = Field(
        default=0, description="How many PII entities were masked (0 if not REDACT)"
    )

    @model_validator(mode="after")
    def validate_action_consistency(self):
        """
        BLOCK → final_response must differ from original_response.
        ALLOW → final_response must equal original_response.
        ESCALATE → final_response must differ and escalation_required must be True.
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
        if self.action == ActionType.ESCALATE and self.final_response == self.original_response:
            raise ValueError(
                "ESCALATE action must hold the original LLM response for review"
            )
        if self.repair_attempts and not self.repair_attempted:
            raise ValueError("repair_attempts requires repair_attempted=True")
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
    risk_breakdown: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per-signal risk breakdown for dashboard display"
    )
    efficiency: Optional[EfficiencyResult] = Field(
        default=None,
        description="Estimated routing, capability, cost, and latency evidence",
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
    efficiency: Optional[EfficiencyResult] = Field(
        default=None,
        description="Structured model-routing and efficiency evidence",
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
    "UseCase", "RiskLevel", "ActionType", "ModelTier", "ComplexityLevel", "BiasType", "ProtectedDimension", "BiasBehavior", "LLMBiasJudgment", "PIIEntityType", "SecretType",
    "ConfidentialCategory",
    # Sub-models
    "PIIEntity", "FlaggedClaim", "SupportingSource", "ModelConfig", "ModelProfile", "ComplexityAssessment", "RoutingResult", "EfficiencyResult",
    "PolicyDecision", "PolicyEvaluationRequest", "InterceptPolicyRequest", "RiskBreakdown",
    # Engine Results
    "InjectionResult", "PIIResult", "PiiTextRequest", "PiiScanResponse",
    "PiiAnonymizeResponse", "SecretFinding", "SecretResult", "SecretTextRequest",
    "SecretScanResponse", "SecretAnonymizeResponse", "BiasResult", "BiasTextRequest", "BiasScanResponse", "GroundednessResult",
    "ConfidentialFinding", "ConfidentialResult", "ConfidentialTextRequest",
    "ConfidentialScanResponse", "ConfidentialAnonymizeResponse",
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
