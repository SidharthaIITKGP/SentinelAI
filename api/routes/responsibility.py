"""Independent Phase 1 Responsibility Engine test endpoints."""

import logging

from fastapi import APIRouter, HTTPException
from api.schemas import (
    PiiAnonymizeResponse, PiiScanResponse, PiiTextRequest,
    SecretAnonymizeResponse, SecretScanResponse, SecretTextRequest,
    ConfidentialAnonymizeResponse, ConfidentialScanResponse, ConfidentialTextRequest,
    PolicyDecision, PolicyEvaluationRequest,
    SimulatedInterceptRequest, SimulatedInterceptResponse,
    BiasTextRequest, BiasScanResponse,
)
from engines.responsibility.bias_check.bias_detector import (
    BiasDetectorError,
    get_bias_detector,
)
from engines.responsibility.pii_check.confidential_detector import (
    ConfidentialDetectorError, get_confidential_detector,
)
from engines.responsibility.pii_check.pii_detector import PresidioServiceError, get_pii_detector
from engines.responsibility.pii_check.intercept_pipeline import (
    InterceptPipelineError, get_intercept_pipeline,
)
from engines.responsibility.pii_check.secret_detector import SecretDetector, SecretDetectorError
from engines.responsibility.pii_check.policy.engine import PolicyConfigurationError, get_policy_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/responsibility", tags=["responsibility"])


def _scan_response(result) -> dict:
    return {
        "contains_pii": result.found,
        "findings": result.entities,
        "risk_score": result.risk_score,
        "entity_count": result.entity_count,
        "high_risk_entities": result.high_risk_entities,
        "scan_target": result.scan_target,
    }


def _secret_scan_response(result) -> dict:
    return {
        "contains_secrets": result.found,
        "findings": result.findings,
        "risk_score": result.risk_score,
        "secret_count": result.secret_count,
        "high_risk_secret_types": result.high_risk_secret_types,
        "scan_target": result.scan_target,
    }


def _confidential_scan_response(result) -> dict:
    return {
        "contains_confidential_information": result.detected,
        "findings": result.findings,
        "risk_score": result.risk_score,
        "finding_count": result.finding_count,
        "scan_target": result.scan_target,
    }


@router.post("/bias/scan", response_model=BiasScanResponse)
async def scan_bias(request: BiasTextRequest) -> dict:
    """Inspect an LLM response for evidence of endorsed discriminatory bias."""
    try:
        result = get_bias_detector().scan(request.text, scan_target=request.scan_target)
        return {"detected": result.detected, "risk_score": result.risk_score,
                "protected_dimensions": result.protected_dimensions, "behaviors": result.behaviors,
                "evidence": result.evidence, "toxicity_score": result.toxicity_score,
                "identity_hate_score": result.identity_hate_score,
                "detection_method": result.detection_method, "scan_target": request.scan_target}
    except (BiasDetectorError, ValueError):
        logger.error("Bias scan request failed")
        raise HTTPException(status_code=503, detail="Bias scanning service is unavailable") from None


@router.post("/scan", response_model=PiiScanResponse)
async def scan_pii(request: PiiTextRequest) -> dict:
    """Scan user text with Microsoft Presidio without exposing detected values."""
    try:
        return _scan_response(get_pii_detector().scan(request.text, scan_target=request.scan_target))
    except (PresidioServiceError, ValueError):
        logger.error("Responsibility scan request failed")
        raise HTTPException(status_code=503, detail="PII scanning service is unavailable") from None


@router.post("/anonymize", response_model=PiiAnonymizeResponse)
async def anonymize_pii(request: PiiTextRequest) -> dict:
    """Scan then redact PII using typed placeholders such as ``<EMAIL_ADDRESS>``."""
    try:
        result, anonymized_text = get_pii_detector().anonymize(
            request.text, scan_target=request.scan_target
        )
        return {**_scan_response(result), "anonymized_text": anonymized_text}
    except (PresidioServiceError, ValueError):
        logger.error("Responsibility anonymization request failed")
        raise HTTPException(status_code=503, detail="PII anonymization service is unavailable") from None


@router.post("/secrets/scan", response_model=SecretScanResponse)
async def scan_secrets(request: SecretTextRequest) -> dict:
    """Detect common credentials without returning their values."""
    try:
        return _secret_scan_response(SecretDetector().scan(request.text, scan_target=request.scan_target))
    except (SecretDetectorError, ValueError):
        logger.error("Secret scan request failed")
        raise HTTPException(status_code=503, detail="Credential scanning service is unavailable") from None


@router.post("/secrets/anonymize", response_model=SecretAnonymizeResponse)
async def anonymize_secrets(request: SecretTextRequest) -> dict:
    """Redact credential values with category-preserving placeholders."""
    try:
        result, anonymized_text = SecretDetector().anonymize(request.text, scan_target=request.scan_target)
        return {**_secret_scan_response(result), "anonymized_text": anonymized_text}
    except (SecretDetectorError, ValueError):
        logger.error("Secret anonymization request failed")
        raise HTTPException(status_code=503, detail="Credential anonymization service is unavailable") from None


@router.post("/confidential/scan", response_model=ConfidentialScanResponse)
async def scan_confidential_information(request: ConfidentialTextRequest) -> dict:
    """Classify contextual confidential information without returning source text."""
    try:
        return _confidential_scan_response(
            get_confidential_detector().scan(request.text, scan_target=request.scan_target)
        )
    except (ConfidentialDetectorError, ValueError):
        logger.error("Confidential-information scan request failed")
        raise HTTPException(
            status_code=503, detail="Confidential-information scanning service is unavailable"
        ) from None


@router.post("/confidential/anonymize", response_model=ConfidentialAnonymizeResponse)
async def anonymize_confidential_information(request: ConfidentialTextRequest) -> dict:
    """Replace contextually confidential sentence segments with typed placeholders."""
    try:
        result, anonymized_text = get_confidential_detector().anonymize(
            request.text, scan_target=request.scan_target
        )
        return {**_confidential_scan_response(result), "anonymized_text": anonymized_text}
    except (ConfidentialDetectorError, ValueError):
        logger.error("Confidential-information anonymization request failed")
        raise HTTPException(
            status_code=503, detail="Confidential-information anonymization service is unavailable"
        ) from None


@router.post("/policy/evaluate", response_model=PolicyDecision)
async def evaluate_policy(request: PolicyEvaluationRequest) -> PolicyDecision:
    """Evaluate Phase 4 policy from safe aggregate scores and detector signals only."""
    try:
        return get_policy_engine().evaluate(request)
    except PolicyConfigurationError:
        logger.error("Responsibility policy evaluation failed")
        raise HTTPException(status_code=503, detail="Policy evaluation service is unavailable") from None


@router.post("/intercept", response_model=SimulatedInterceptResponse)
async def simulated_intercept(request: SimulatedInterceptRequest) -> SimulatedInterceptResponse:
    """Run the no-LLM detector-to-policy integration pipeline for external text."""
    try:
        return get_intercept_pipeline().intercept(request)
    except InterceptPipelineError:
        logger.error("Simulated responsibility intercept failed")
        raise HTTPException(status_code=503, detail="Responsibility intercept service is unavailable") from None
