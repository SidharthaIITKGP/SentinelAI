"""Simulated no-LLM intercept pipeline for Responsibility Engine integration tests."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from api.schemas import (
    InterceptEvidence, InterceptPolicyRequest, RiskLevel, SecretType,
    SimulatedInterceptRequest, SimulatedInterceptResponse,
)
from engines.responsibility.pii_check.confidential_detector import (
    ConfidentialDetectorError, get_confidential_detector,
)
from engines.responsibility.pii_check.pii_detector import PresidioServiceError, get_pii_detector
from engines.responsibility.pii_check.secret_detector import HIGH_RISK_SECRET_TYPES, SecretDetector, SecretDetectorError
from engines.responsibility.pii_check.policy.engine import PolicyConfigurationError, PolicyEngine, get_policy_engine

logger = logging.getLogger(__name__)


class InterceptPipelineError(RuntimeError):
    """Raised when a required detector or the policy engine is unavailable."""


class SimulatedInterceptPipeline:
    """Coordinate existing detectors and policy without calling an LLM.

    The public target is ``external_llm``; existing detector APIs continue to
    receive their supported ``prompt`` target. Evidence contains categories and
    scores only, never the prompt or matched values.
    """

    def __init__(
        self,
        *,
        pii_detector: Any | None = None,
        secret_detector: SecretDetector | None = None,
        confidential_detector: Any | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._pii_detector = pii_detector
        self._secret_detector = secret_detector
        self._confidential_detector = confidential_detector
        self._policy_engine = policy_engine

    def intercept(self, request: SimulatedInterceptRequest) -> SimulatedInterceptResponse:
        """Evaluate a prompt with all detectors and return a safe governance outcome."""
        try:
            pii_detector = self._pii_detector or get_pii_detector()
            secret_detector = self._secret_detector or SecretDetector()
            confidential_detector = self._confidential_detector or get_confidential_detector()
            policy_engine = self._policy_engine or get_policy_engine()
            detector_target = "prompt"
            pii_result = pii_detector.scan(request.text, scan_target=detector_target)
            secret_result = secret_detector.scan(request.text, scan_target=detector_target)
            confidential_result = confidential_detector.scan(request.text, scan_target=detector_target)
            evidence, policy_request = self._aggregate(
                pii_result, secret_result, confidential_result, request, policy_engine
            )
            decision = policy_engine.evaluate_intercept(policy_request)
            evidence = evidence.model_copy(update={
                "policy_rule_ids": decision.policy_rule_ids,
                "policy_reason": decision.reason,
            })
            redacted_prompt = self._redact_if_required(
                request.text, decision.final_action, pii_result.found, secret_result.found,
                pii_detector, secret_detector, detector_target,
            )
        except (
            PresidioServiceError, SecretDetectorError, ConfidentialDetectorError,
            PolicyConfigurationError, ValueError,
        ) as exc:
            logger.error("Simulated intercept pipeline unavailable")
            raise InterceptPipelineError("Simulated intercept pipeline is unavailable") from exc

        return SimulatedInterceptResponse(
            action_taken=decision.final_action,
            risk_score=policy_request.risk_score,
            risk_level=self._risk_level(policy_request.risk_score),
            evidence=evidence,
            governed=True,
            redacted_prompt=redacted_prompt,
        )

    @staticmethod
    def _aggregate(pii_result, secret_result, confidential_result, request, policy_engine):
        pii_types = sorted({str(item.entity_type) for item in pii_result.entities})
        secret_types = sorted({str(item.secret_type) for item in secret_result.findings})
        confidential_categories = sorted({str(item.category) for item in confidential_result.findings})
        known_secret = any(str(item.secret_type) in HIGH_RISK_SECRET_TYPES for item in secret_result.findings)
        possible_secret = any(str(item.secret_type) == SecretType.POSSIBLE_SECRET.value for item in secret_result.findings)
        detected_scores = (pii_result.risk_score, secret_result.risk_score, confidential_result.risk_score)
        signal_count = sum((pii_result.found, secret_result.found, confidential_result.detected))
        risk_score = max(detected_scores, default=0.0)
        if known_secret:
            risk_score = 1.0
        elif signal_count > 1:
            risk_score = min(1.0, risk_score + policy_engine.intercept_risk_increment() * (signal_count - 1))
        risk_score = round(float(risk_score), 4)
        policy_request = InterceptPolicyRequest(
            use_case=request.use_case,
            scan_target=request.scan_target,
            risk_score=risk_score,
            pii_detected=pii_result.found,
            secret_detected=secret_result.found,
            confidential_detected=confidential_result.detected,
            known_high_confidence_secret=known_secret,
            possible_secret=possible_secret,
            signal_count=signal_count,
        )
        return (
            InterceptEvidence(
                pii_detected=pii_result.found,
                secret_detected=secret_result.found,
                confidential_detected=confidential_result.detected,
                pii_types=pii_types,
                secret_types=secret_types,
                confidential_categories=confidential_categories,
                max_confidence=max(detected_scores, default=0.0),
                policy_rule_ids=[],
                policy_reason="",
            ),
            policy_request,
        )

    @staticmethod
    def _redact_if_required(
        text: str, action: str, has_pii: bool, has_secret: bool,
        pii_detector: Any, secret_detector: SecretDetector, detector_target: str,
    ) -> str | None:
        if str(action) != "REDACT":
            return None
        redacted = text
        if has_secret:
            _, redacted = secret_detector.anonymize(redacted, scan_target=detector_target)
        if has_pii:
            _, redacted = pii_detector.anonymize(redacted, scan_target=detector_target)
        return redacted

    @staticmethod
    def _risk_level(score: float) -> RiskLevel:
        if score > 0.65:
            return RiskLevel.HIGH
        if score > 0.35:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


@lru_cache(maxsize=1)
def get_intercept_pipeline() -> SimulatedInterceptPipeline:
    """Return one stateless simulated pipeline per application process."""
    return SimulatedInterceptPipeline()
