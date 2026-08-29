"""Deterministic, configuration-driven policy evaluator for Phase 4.

The evaluator only accepts aggregate scores and boolean detector outcomes. It
does not receive, log, or retain prompt text, responses, credentials, or PII.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from api.schemas import (
    ActionType, InterceptPolicyRequest, PolicyDecision, PolicyEvaluationRequest,
)


class PolicyConfigurationError(RuntimeError):
    """Raised when the local, reviewable policy configuration is invalid."""


DEFAULT_POLICY_FILE = Path(__file__).with_name("thresholds.yaml")


class PolicyEngine:
    """Apply a use-case policy to safe responsibility-engine signals."""

    def __init__(self, policy_file: Path | str = DEFAULT_POLICY_FILE) -> None:
        self._path = Path(policy_file)
        self._policy = self._load_policy()

    def _load_policy(self) -> dict[str, Any]:
        try:
            with self._path.open(encoding="utf-8") as policy_handle:
                policy = yaml.safe_load(policy_handle)
        except (OSError, yaml.YAMLError) as exc:
            raise PolicyConfigurationError("Policy configuration is unavailable") from exc

        if not isinstance(policy, dict) or not isinstance(policy.get("use_cases"), dict):
            raise PolicyConfigurationError("Policy configuration has no use-case rules")

        for name, rules in policy["use_cases"].items():
            if not isinstance(rules, dict):
                raise PolicyConfigurationError(f"Policy rules for {name} are invalid")
            try:
                block_at, escalate_at = float(rules["block_at"]), float(rules["escalate_at"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PolicyConfigurationError(f"Policy thresholds for {name} are invalid") from exc
            if not 0.0 <= escalate_at <= block_at <= 1.0:
                raise PolicyConfigurationError(f"Policy thresholds for {name} are invalid")
            for action_key in ("sensitive_data_action", "confidential_action", "bias_action"):
                try:
                    ActionType(rules[action_key])
                except (KeyError, ValueError) as exc:
                    raise PolicyConfigurationError(f"Policy action {action_key} for {name} is invalid") from exc
        self._validate_intercept_policy(policy)
        return policy

    @staticmethod
    def _validate_intercept_policy(policy: dict[str, Any]) -> None:
        try:
            increment = float(policy["intercept"]["risk_aggregation"]["multi_signal_increment"])
            targets = policy["intercept"]["targets"]
            rules = targets["external_llm"]
            minimum = int(rules["multi_signal_minimum"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicyConfigurationError("Intercept policy configuration is invalid") from exc
        if not 0.0 <= increment <= 1.0 or minimum < 2:
            raise PolicyConfigurationError("Intercept policy configuration is invalid")
        for action_key in (
            "known_secret_action", "possible_secret_action", "generic_secret_action",
            "pii_action", "confidential_action", "multi_signal_action",
        ):
            try:
                ActionType(rules[action_key])
            except (KeyError, ValueError) as exc:
                raise PolicyConfigurationError("Intercept policy configuration is invalid") from exc

    def evaluate(self, request: PolicyEvaluationRequest) -> PolicyDecision:
        """Return the mandatory action; high risk overrides lower-priority signals."""
        try:
            use_case = getattr(request.use_case, "value", request.use_case)
            rules = self._policy["use_cases"][use_case]
        except KeyError as exc:
            raise PolicyConfigurationError("No policy exists for the requested use case") from exc

        if request.risk_score >= float(rules["block_at"]):
            action, threshold, reason = (
                ActionType.BLOCK,
                float(rules["block_at"]),
                "Risk score meets the configured block threshold.",
            )
        elif request.risk_score >= float(rules["escalate_at"]):
            action, threshold, reason = (
                ActionType.ESCALATE,
                float(rules["escalate_at"]),
                "Risk score meets the configured escalation threshold.",
            )
        elif request.secrets_detected or request.pii_detected:
            action, threshold, reason = (
                ActionType(rules["sensitive_data_action"]),
                0.0,
                "Sensitive-data detector signal requires the configured protective action.",
            )
        elif request.confidential_detected:
            action, threshold, reason = (
                ActionType(rules["confidential_action"]),
                0.0,
                "Confidential-information detector signal requires the configured action.",
            )
        elif request.bias_detected:
            action, threshold, reason = (
                ActionType(rules["bias_action"]), 0.0,
                "Bias detector signal requires the configured review action.",
            )
        else:
            action, threshold, reason = (
                ActionType.ALLOW,
                0.0,
                "No configured risk threshold or protective detector signal was triggered.",
            )

        return PolicyDecision(
            approved=request.proposed_action == action,
            final_action=action,
            reason=reason,
            policy_file="engines/responsibility/pii_check/policy/thresholds.yaml",
            threshold_applied=threshold,
            policy_rule_ids=["use_case.risk_threshold"] if threshold else ["use_case.protective_signal"],
        )

    def intercept_risk_increment(self) -> float:
        """Return the reviewed extra-risk increment for multiple detector families."""
        return float(self._policy["intercept"]["risk_aggregation"]["multi_signal_increment"])

    def evaluate_intercept(self, request: InterceptPolicyRequest) -> PolicyDecision:
        """Apply external-target rules to aggregate evidence, never source text."""
        try:
            rules = self._policy["intercept"]["targets"][request.scan_target]
        except KeyError as exc:
            raise PolicyConfigurationError("No intercept policy exists for the requested target") from exc

        candidates = (
            (request.known_high_confidence_secret, "known_secret_action", "intercept.known_secret"),
            (request.possible_secret, "possible_secret_action", "intercept.possible_secret"),
            (
                request.signal_count >= int(rules["multi_signal_minimum"]),
                "multi_signal_action",
                "intercept.multiple_detector_families",
            ),
            (request.confidential_detected, "confidential_action", "intercept.confidential_information"),
            (request.pii_detected, "pii_action", "intercept.pii"),
            (request.secret_detected, "generic_secret_action", "intercept.generic_secret"),
        )
        for matched, action_key, rule_id in candidates:
            if matched:
                action = ActionType(rules[action_key])
                return PolicyDecision(
                    approved=request.proposed_action == action,
                    final_action=action,
                    reason="Configured external-target protective rule was triggered.",
                    policy_file="engines/responsibility/pii_check/policy/thresholds.yaml",
                    threshold_applied=0.0,
                    policy_rule_ids=[rule_id],
                )

        # No detector-specific rule matched; score thresholds remain the safe default.
        evaluation = PolicyEvaluationRequest(
            use_case=request.use_case,
            risk_score=request.risk_score,
            proposed_action=request.proposed_action,
        )
        return self.evaluate(evaluation)


@lru_cache(maxsize=1)
def get_policy_engine() -> PolicyEngine:
    """Return one immutable policy evaluator per application process."""
    return PolicyEngine()
