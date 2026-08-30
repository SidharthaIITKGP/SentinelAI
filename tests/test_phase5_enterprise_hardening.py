"""Phase 5 enterprise security, privacy, isolation, and health regressions."""

from __future__ import annotations

import json
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx

import core.main as main
import core.pipeline as pipeline
from api.routes import feedback as feedback_routes
from api.routes import intercept as intercept_routes
from api.routes import metrics as metrics_routes
from api.routes import reviews as review_routes
from api.schemas import (
    FeedbackRecord, ReviewMetrics, ReviewRecord, ReviewStatus, ReviewSummary,
)
from core.config import ConfigurationError, load_runtime_config
from core.security import authenticate_reviewer, authenticate_tenant
from data import audit_privacy
from data import audit_logger
from data.review_store import ReviewConflictError, ReviewNotFoundError

NOW = datetime.now(timezone.utc)
HELD = "private held recommendation"
HOLDING = "This response is being held for human review."


@pytest.fixture
def secured_env(monkeypatch):
    monkeypatch.setenv("SENTINEL_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "SENTINEL_TENANT_API_KEYS_JSON",
        json.dumps({"tenant-a-secret": "tenant_a", "tenant-b-secret": "tenant_b"}),
    )
    monkeypatch.setenv(
        "SENTINEL_REVIEWER_API_KEYS_JSON",
        json.dumps({
            "reviewer-a-secret": {"reviewer_id": "reviewer_a", "allowed_tenants": ["tenant_a"]},
            "reviewer-b-secret": {"reviewer_id": "reviewer_b", "allowed_tenants": ["tenant_b"]},
        }),
    )
    monkeypatch.setenv("SENTINEL_AUDIT_CONTENT_MODE", "redacted")


@pytest.fixture
def client():
    class LocalASGIClient:
        @staticmethod
        def request(method, path, **kwargs):
            async def send():
                transport = httpx.ASGITransport(app=main.app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as async_client:
                    return await async_client.request(method, path, **kwargs)
            return asyncio.run(send())

        def get(self, path, **kwargs):
            return self.request("GET", path, **kwargs)

        def post(self, path, **kwargs):
            return self.request("POST", path, **kwargs)

        def options(self, path, **kwargs):
            return self.request("OPTIONS", path, **kwargs)

    return LocalASGIClient()


def _record(request_id="review-a", tenant_id="tenant_a", status="PENDING"):
    return ReviewRecord(
        review_id=f"id-{request_id}", request_id=request_id, tenant_id=tenant_id,
        use_case="finance_tool", status=status, sentinelai_action="ESCALATE",
        original_response=HELD, holding_response=HOLDING, risk_level="HIGH",
        risk_score=0.9, action_evidence={"routing_failure": True},
        groundedness_evidence={"verdict": "INSUFFICIENT_EVIDENCE"},
        efficiency_evidence={"generation_performed": False}, created_at=NOW,
    )


class IsolatedStore:
    def __init__(self):
        self.records = {
            "review-a": _record(),
            "review-b": _record("review-b", "tenant_b"),
        }
        self.feedback = {"review-a": [], "review-b": []}
        self.enqueued = []

    @staticmethod
    def _allowed(record, allowed):
        return allowed is None or record.tenant_id in allowed

    async def enqueue(self, audit):
        self.enqueued.append(audit)

    async def list(self, status, use_case, limit, allowed=None):
        status = getattr(status, "value", status)
        rows = [r for r in self.records.values() if r.status == status and self._allowed(r, allowed)]
        return [ReviewSummary(**r.model_dump(exclude={
            "original_response", "action_evidence", "groundedness_evidence",
            "efficiency_evidence", "reviewer_id", "reviewer_notes", "edited_response",
        })) for r in rows[:limit]]

    async def get(self, request_id, allowed=None):
        record = self.records.get(request_id)
        if record is None or not self._allowed(record, allowed):
            raise ReviewNotFoundError(request_id)
        return record

    async def decide(self, request_id, decision, allowed=None):
        record = await self.get(request_id, allowed)
        if record.status != "PENDING":
            raise ReviewConflictError(request_id)
        status = {"APPROVE": "APPROVED", "EDIT": "EDITED", "REJECT": "REJECTED"}[decision.decision]
        record = record.model_copy(update={
            "status": status, "reviewer_id": decision.reviewer_id,
            "edited_response": decision.edited_response, "reviewed_at": NOW,
        })
        self.records[request_id] = record
        self.feedback[request_id].append(decision.reviewer_id)
        return record

    async def metrics(self, allowed=None):
        rows = [r for r in self.records.values() if self._allowed(r, allowed)]
        pending = sum(r.status == "PENDING" for r in rows)
        completed = len(rows) - pending
        return ReviewMetrics(
            total_reviews=len(rows), pending_reviews=pending,
            completed_reviews=completed,
        )

    async def create_feedback(self, item, allowed=None):
        record = await self.get(item.request_id, allowed)
        self.feedback[record.request_id].append(item.reviewer_id)
        return "feedback-id"

    async def get_feedback(self, request_id, allowed=None):
        record = await self.get(request_id, allowed)
        return [FeedbackRecord(
            feedback_id="f-1", request_id=record.request_id,
            sentinelai_action="ESCALATE", correct_action="ALLOW",
            reviewer_id="reviewer_a", created_at=NOW,
        )]


@pytest.fixture
def isolated_store(monkeypatch):
    store = IsolatedStore()
    monkeypatch.setattr(review_routes, "review_store", store)
    monkeypatch.setattr(feedback_routes, "review_store", store)
    return store


def _pipeline_result(action="ALLOW", tenant_id="tenant_a"):
    final = "approved answer" if action == "ALLOW" else HOLDING
    action_result = SimpleNamespace(
        action=action, final_response=final, original_response="approved answer",
        evidence={}, escalation_required=action == "ESCALATE",
    )
    breakdown = SimpleNamespace(
        injection_score=0.0, pii_prompt_score=0.0, pii_response_score=0.0,
        groundedness_risk=0.0, bias_score=0.0, dominant_signal="none",
    )
    audit = SimpleNamespace(
        request_id="request-auth", tenant_id=tenant_id,
        risk_score=SimpleNamespace(overall=0.1, level="LOW", breakdown=breakdown),
        latency_ms=5, efficiency=None,
    )
    return action_result, audit


def _patch_intercept(monkeypatch, store, action="ALLOW"):
    captured = {}

    async def run(request):
        captured["request"] = request
        return _pipeline_result(action, request.tenant_id)

    async def log(audit):
        captured["audit"] = audit
        return audit.request_id

    monkeypatch.setattr(intercept_routes, "run_pipeline", run)
    monkeypatch.setattr(intercept_routes, "log_request", log)
    monkeypatch.setattr(intercept_routes, "review_store", store)
    return captured


def _intercept_body(tenant="tenant_a"):
    return {"prompt": "safe request", "use_case": "customer_chatbot", "tenant_id": tenant, "user_id": "u"}


@pytest.mark.usefixtures("secured_env")
@pytest.mark.parametrize("headers", [{}, {"X-Sentinel-API-Key": "invalid-key"}])
def test_missing_or_invalid_tenant_key_is_401(client, monkeypatch, headers):
    _patch_intercept(monkeypatch, IsolatedStore())
    response = client.post("/intercept", json=_intercept_body(), headers=headers)
    assert response.status_code == 401
    assert "invalid-key" not in response.text


@pytest.mark.usefixtures("secured_env")
def test_valid_tenant_key_authenticates_and_is_persisted(client, monkeypatch):
    captured = _patch_intercept(monkeypatch, IsolatedStore())
    response = client.post(
        "/intercept", json=_intercept_body(),
        headers={"X-Sentinel-API-Key": "tenant-a-secret"},
    )
    assert response.status_code == 200
    assert captured["request"].tenant_id == "tenant_a"
    assert captured["audit"].tenant_id == "tenant_a"


@pytest.mark.usefixtures("secured_env")
def test_tenant_body_spoof_is_403(client, monkeypatch):
    _patch_intercept(monkeypatch, IsolatedStore())
    response = client.post(
        "/intercept", json=_intercept_body("tenant_b"),
        headers={"X-Sentinel-API-Key": "tenant-a-secret"},
    )
    assert response.status_code == 403


@pytest.mark.usefixtures("secured_env")
def test_authenticated_escalation_review_uses_authenticated_tenant(client, monkeypatch):
    store = IsolatedStore()
    _patch_intercept(monkeypatch, store, "ESCALATE")
    response = client.post(
        "/intercept", json=_intercept_body(),
        headers={"X-Sentinel-API-Key": "tenant-a-secret"},
    )
    assert response.status_code == 200
    assert store.enqueued[0].tenant_id == "tenant_a"


@pytest.mark.usefixtures("secured_env")
def test_api_key_never_appears_in_errors_or_logs(client, monkeypatch, caplog):
    secret = "not-a-real-key-but-sensitive"
    caplog.set_level(logging.DEBUG)
    _patch_intercept(monkeypatch, IsolatedStore())
    response = client.post(
        "/intercept", json=_intercept_body(), headers={"X-Sentinel-API-Key": secret}
    )
    assert response.status_code == 401
    assert secret not in response.text
    assert secret not in caplog.text


@pytest.mark.asyncio
@pytest.mark.usefixtures("secured_env")
async def test_security_dependencies_return_mapped_identities():
    tenant = await authenticate_tenant("tenant-a-secret")
    reviewer = await authenticate_reviewer("reviewer-a-secret")
    assert tenant.tenant_id == "tenant_a"
    assert reviewer.reviewer_id == "reviewer_a"
    assert reviewer.allowed_tenants == ("tenant_a",)


@pytest.mark.usefixtures("secured_env")
@pytest.mark.parametrize("path", [
    "/reviews", "/reviews/review-a", "/reviews/review-a/resolution",
    "/reviews/metrics", "/feedback/review-a",
])
def test_anonymous_reviewer_access_is_blocked(client, isolated_store, path):
    assert client.get(path).status_code == 401


@pytest.mark.usefixtures("secured_env")
def test_tenant_key_cannot_be_used_as_reviewer_key(client, isolated_store):
    response = client.get(
        "/reviews", headers={"X-Sentinel-Reviewer-Key": "tenant-a-secret"}
    )
    assert response.status_code == 401


@pytest.mark.usefixtures("secured_env")
def test_valid_reviewer_sees_only_allowed_tenant(client, isolated_store):
    response = client.get(
        "/reviews", headers={"X-Sentinel-Reviewer-Key": "reviewer-a-secret"}
    )
    assert response.status_code == 200
    assert [item["tenant_id"] for item in response.json()] == ["tenant_a"]


@pytest.mark.usefixtures("secured_env")
@pytest.mark.parametrize("path", [
    "/reviews/review-b", "/reviews/review-b/resolution", "/feedback/review-b",
])
def test_cross_tenant_reviewer_access_is_not_found(client, isolated_store, path):
    response = client.get(path, headers={"X-Sentinel-Reviewer-Key": "reviewer-a-secret"})
    assert response.status_code == 404
    assert HELD not in response.text


@pytest.mark.usefixtures("secured_env")
def test_reviewer_id_spoofing_is_overridden(client, isolated_store):
    response = client.post(
        "/reviews/review-a/decision",
        headers={"X-Sentinel-Reviewer-Key": "reviewer-a-secret"},
        json={"decision": "APPROVE", "reviewer_id": "spoofed-reviewer"},
    )
    assert response.status_code == 200
    assert response.json()["reviewer_id"] == "reviewer_a"


@pytest.mark.usefixtures("secured_env")
def test_review_metrics_are_tenant_scoped(client, isolated_store):
    response = client.get(
        "/reviews/metrics", headers={"X-Sentinel-Reviewer-Key": "reviewer-a-secret"}
    )
    assert response.status_code == 200
    assert response.json()["total_reviews"] == 1


@pytest.mark.usefixtures("secured_env")
def test_feedback_is_tenant_scoped_and_reviewer_id_derived(client, isolated_store):
    denied = client.post(
        "/feedback", headers={"X-Sentinel-Reviewer-Key": "reviewer-a-secret"},
        json={"request_id": "review-b", "sentinelai_action": "ESCALATE", "correct_action": "ALLOW", "reviewer_id": "spoof"},
    )
    allowed = client.post(
        "/feedback", headers={"X-Sentinel-Reviewer-Key": "reviewer-a-secret"},
        json={"request_id": "review-a", "sentinelai_action": "ESCALATE", "correct_action": "ALLOW", "reviewer_id": "spoof"},
    )
    assert denied.status_code == 404
    assert allowed.status_code == 200
    assert isolated_store.feedback["review-a"] == ["reviewer_a"]


@pytest.mark.usefixtures("secured_env")
def test_audit_and_governance_metrics_receive_authenticated_tenant(client, monkeypatch):
    recent = AsyncMock(return_value=[])
    summary = AsyncMock(return_value=metrics_routes.MetricsSummary(
        period="24h", period_start=NOW, period_end=NOW
    ))
    monkeypatch.setattr(metrics_routes, "get_recent_logs", recent)
    monkeypatch.setattr(metrics_routes, "get_metrics_summary", summary)
    headers = {"X-Sentinel-API-Key": "tenant-a-secret"}
    assert client.get("/audit/recent", headers=headers).status_code == 200
    assert client.get("/metrics", headers=headers).status_code == 200
    recent.assert_awaited_once_with(limit=20, tenant_id="tenant_a")
    summary.assert_awaited_once_with(period="24h", tenant_id="tenant_a")


@pytest.mark.parametrize("sensitive", [
    "Contact person@example.com", "Employee SSN is 123-45-6789",
    "api_key=ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ",
])
def test_default_redacted_audit_mode_removes_sensitive_content(monkeypatch, sensitive):
    monkeypatch.delenv("SENTINEL_AUDIT_CONTENT_MODE", raising=False)
    stored = audit_privacy.prepare_audit_content(sensitive, sensitive, sensitive)
    assert stored.mode == "redacted"
    assert sensitive not in {stored.prompt, stored.llm_response, stored.final_response}


def test_sanitizer_failure_never_falls_back_to_raw(monkeypatch):
    raw = "person@example.com must never survive"
    monkeypatch.setenv("SENTINEL_AUDIT_CONTENT_MODE", "redacted")
    monkeypatch.setattr(audit_privacy, "get_pii_detector", lambda: (_ for _ in ()).throw(RuntimeError("failed")))
    stored = audit_privacy.prepare_audit_content(raw, raw, raw)
    assert {stored.prompt, stored.llm_response, stored.final_response} == {audit_privacy.SANITIZATION_FAILURE}
    assert raw not in repr(stored)


def test_metadata_only_stores_no_content_but_keeps_hashes(monkeypatch):
    raw = "private metadata-only value"
    monkeypatch.setenv("SENTINEL_AUDIT_CONTENT_MODE", "metadata_only")
    stored = audit_privacy.prepare_audit_content(raw, raw, raw)
    assert stored.prompt == stored.llm_response == stored.final_response == audit_privacy.METADATA_ONLY
    assert stored.prompt_sha256 == audit_privacy.sha256_text(raw)
    assert stored.prompt_length == stored.llm_response_length == stored.final_response_length == len(raw)


def test_raw_audit_mode_requires_explicit_opt_in(monkeypatch):
    raw = "explicit raw audit value"
    monkeypatch.setenv("SENTINEL_AUDIT_CONTENT_MODE", "raw")
    stored = audit_privacy.prepare_audit_content(raw, raw, raw)
    assert stored.mode == "raw" and stored.prompt == raw


def test_hashes_are_deterministic_and_distinguish_content():
    assert audit_privacy.sha256_text("same") == audit_privacy.sha256_text("same")
    assert audit_privacy.sha256_text("same") != audit_privacy.sha256_text("different")
    assert len(audit_privacy.sha256_text("same")) == 64


@pytest.mark.parametrize("mode", ["redacted", "metadata_only"])
def test_audit_evidence_metadata_does_not_retain_free_text(mode):
    evidence = {
        "confidence": 0.9,
        "injection": {"flagged_text": "person@example.com"},
        "flagged_segments": ["123-45-6789"],
    }
    safe = audit_privacy.sanitize_evidence_metadata(evidence, mode)
    assert safe["confidence"] == 0.9
    assert "person@example.com" not in repr(safe)
    assert "123-45-6789" not in repr(safe)


@pytest.mark.asyncio
async def test_audit_persistence_uses_privacy_preparation(monkeypatch):
    monkeypatch.setenv("SENTINEL_AUDIT_CONTENT_MODE", "metadata_only")
    captured = {}

    class Connection:
        async def execute(self, *args):
            captured["args"] = args

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *args):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    monkeypatch.setattr(audit_logger, "_get_pool", AsyncMock(return_value=Pool()))
    audit = SimpleNamespace(
        request_id="00000000-0000-0000-0000-000000000001", timestamp=NOW,
        tenant_id="tenant_a", use_case="customer_chatbot",
        prompt="private prompt", llm_response="private model output",
        final_response="private final output", tokens_total=3, model_used="model",
        latency_ms=4,
        risk_score=SimpleNamespace(overall=0.1, level="LOW", breakdown={}),
        action=SimpleNamespace(action="ALLOW", evidence={}),
        groundedness=SimpleNamespace(flagged_claims=[]),
        pii_in_response=SimpleNamespace(found=False),
    )
    await audit_logger.log_request(audit)
    args = captured["args"]
    assert args[5:8] == (
        audit_privacy.METADATA_ONLY,
        audit_privacy.METADATA_ONLY,
        audit_privacy.METADATA_ONLY,
    )
    assert args[11] == "metadata_only"
    assert "private prompt" not in args


def test_raw_mode_warning_is_static_and_contains_no_content(caplog):
    caplog.set_level(logging.WARNING)
    main.warn_for_raw_audit_mode("raw")
    assert "Raw audit content storage is enabled." in caplog.text
    assert HELD not in caplog.text


@pytest.mark.parametrize("name,value", [
    ("SENTINEL_AUTH_ENABLED", "sometimes"),
    ("SENTINEL_TENANT_API_KEYS_JSON", "not-json"),
    ("SENTINEL_AUDIT_CONTENT_MODE", "encrypted"),
])
def test_invalid_startup_configuration_fails_clearly(monkeypatch, name, value):
    monkeypatch.setenv("SENTINEL_AUTH_ENABLED", "false")
    monkeypatch.setenv("SENTINEL_TENANT_API_KEYS_JSON", "{}")
    monkeypatch.setenv("SENTINEL_REVIEWER_API_KEYS_JSON", "{}")
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError, match=name):
        load_runtime_config()


def test_auth_enabled_requires_both_credential_maps(monkeypatch):
    monkeypatch.setenv("SENTINEL_AUTH_ENABLED", "true")
    monkeypatch.setenv("SENTINEL_TENANT_API_KEYS_JSON", "{}")
    monkeypatch.setenv("SENTINEL_REVIEWER_API_KEYS_JSON", "{}")
    with pytest.raises(ConfigurationError, match="TENANT_API_KEYS"):
        load_runtime_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("postgres,qdrant,llm,expected", [
    (True, True, True, "ok"), (False, True, True, "degraded"),
    (True, False, True, "degraded"), (False, False, False, "unhealthy"),
])
async def test_health_reflects_real_dependency_state(monkeypatch, postgres, qdrant, llm, expected):
    monkeypatch.setattr(main.health, "check_postgresql", AsyncMock(return_value=postgres))
    monkeypatch.setattr(main.health, "check_qdrant", AsyncMock(return_value=qdrant))
    monkeypatch.setattr(main.health, "llm_is_configured", lambda: llm)
    response = await main.health_check()
    assert response.status == expected
    assert "redis" not in response.services and "opa" not in response.services


@pytest.mark.asyncio
async def test_health_never_calls_llm_generation(monkeypatch):
    generation = AsyncMock()
    monkeypatch.setattr(pipeline, "_call_llm", generation)
    monkeypatch.setattr(main.health, "check_postgresql", AsyncMock(return_value=True))
    monkeypatch.setattr(main.health, "check_qdrant", AsyncMock(return_value=True))
    monkeypatch.setattr(main.health, "llm_is_configured", lambda: True)
    assert (await main.health_check()).status == "ok"
    generation.assert_not_called()


def test_cors_uses_explicit_origin_and_required_headers(client):
    response = client.options(
        "/intercept",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Sentinel-API-Key,Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-origin"] != "*"
    assert "x-sentinel-api-key" in response.headers["access-control-allow-headers"].lower()


def test_active_runtime_has_no_redis_or_false_policy_telemetry_claims():
    compose = Path("docker-compose.yml").read_text().lower()
    readme = Path("README.md").read_text()
    assert "redis:" not in compose and "redis_url" not in compose
    assert "Deterministic YAML policy-as-code" in readme
    assert "OpenTelemetry exporters" in readme and "not features claimed" in readme


def test_environment_example_and_dashboard_header_support_exist():
    example = Path(".env.example").read_text()
    dashboard = Path("dashboard/src/components/shared.jsx").read_text()
    assert "SENTINEL_TENANT_API_KEYS_JSON" in example
    assert "SENTINEL_REVIEWER_API_KEYS_JSON" in example
    assert "SENTINEL_AUDIT_CONTENT_MODE=redacted" in example
    assert "VITE_SENTINEL_API_KEY" in dashboard
    assert "X-Sentinel-Reviewer-Key" not in dashboard


def test_schema_persists_content_hashes_and_mode():
    schema = Path("data/schema.sql").read_text()
    assert all(field in schema for field in (
        "prompt_sha256", "llm_response_sha256", "final_response_sha256",
        "audit_content_mode", "prompt_length", "llm_response_length",
        "final_response_length",
    ))


def test_phase3_and_phase4_security_invariants_remain_in_focused_suites():
    phase3 = Path("tests/test_phase3_efficiency_routing.py").read_text()
    phase4 = Path("tests/test_phase4_human_review.py").read_text()
    assert "llm.assert_not_called()" in phase3
    assert "test_hard_routing_failure_skips_llm_and_enters_review_queue" in phase4
    assert "assert SECRET not in result.response" in phase4
