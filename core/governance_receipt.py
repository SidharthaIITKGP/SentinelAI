"""Build compact governance receipts from the authoritative audit record."""

from __future__ import annotations

from typing import Any

from api.schemas import (
    GovernanceEvidenceSource,
    GovernanceReceipt,
    GroundednessVerdict,
    ResponsibilityFindings,
)


def _values(items: Any, attribute: str) -> list[str]:
    """Return unique enum/string metadata without retaining matched values."""
    values = {
        str(getattr(item, attribute, ""))
        for item in (items or [])
        if getattr(item, attribute, None)
    }
    return sorted(values)


def build_governance_receipt(audit_entry: Any, request_id: str | None = None) -> GovernanceReceipt:
    """Project an audit entry into a safe, compact customer receipt."""
    action = audit_entry.action
    policy = audit_entry.policy_decision
    groundedness = audit_entry.groundedness
    efficiency = getattr(audit_entry, "efficiency", None)
    action_evidence = getattr(action, "evidence", {}) or {}
    explanation = list(getattr(efficiency, "explanation", []) or [])

    prompt_entities = getattr(getattr(audit_entry, "pii_in_prompt", None), "entities", [])
    response_entities = getattr(getattr(audit_entry, "pii_in_response", None), "entities", [])
    bias = getattr(audit_entry, "bias", None)
    sources = [
        GovernanceEvidenceSource(doc_id=source.doc_id, title=source.title)
        for source in (getattr(groundedness, "supporting_sources", []) or [])
    ]

    routing_reason = action_evidence.get("routing_reason")
    if not routing_reason and explanation:
        routing_reason = explanation[0]

    return GovernanceReceipt(
        request_id=request_id or audit_entry.request_id,
        final_action=action.action,
        use_case=audit_entry.use_case,
        risk_level=audit_entry.risk_score.level,
        risk_score=audit_entry.risk_score.overall,
        policy_file=policy.policy_file,
        policy_rule_ids=list(policy.policy_rule_ids),
        policy_reason=policy.reason,
        trust_verdict=getattr(
            groundedness,
            "verdict",
            GroundednessVerdict.INSUFFICIENT_EVIDENCE,
        ),
        responsibility_findings=ResponsibilityFindings(
            injection_detected=bool(getattr(audit_entry.injection, "detected", False)),
            pii_prompt_types=_values(prompt_entities, "entity_type"),
            pii_response_types=_values(response_entities, "entity_type"),
            bias_detected=bool(getattr(bias, "detected", False)),
            bias_types=sorted(str(value) for value in (getattr(bias, "bias_types", []) or [])),
        ),
        selected_model=(
            getattr(efficiency, "selected_model", None)
            or getattr(audit_entry, "model_used", None)
            or None
        ),
        selected_tier=getattr(efficiency, "selected_tier", None),
        routing_reason=routing_reason,
        estimated_cost_usd=getattr(audit_entry, "estimated_cost_usd", None),
        latency_ms=getattr(audit_entry, "latency_ms", 0),
        evidence_sources=sources,
        repair_attempted=bool(getattr(action, "repair_attempted", False)),
        repair_success=bool(action_evidence.get("repair_success", False)),
        review_required=bool(
            getattr(action, "escalation_required", False)
            or getattr(audit_entry, "escalation_required", False)
        ),
    )
