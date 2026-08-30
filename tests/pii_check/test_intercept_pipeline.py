"""No-LLM end-to-end tests for the simulated responsibility intercept pipeline."""

import httpx
import pytest

from api.schemas import SimulatedInterceptRequest
from core.main import app
from engines.responsibility.pii_check.confidential_detector import ContextualConfidentialDetector
from engines.responsibility.pii_check.intercept_pipeline import SimulatedInterceptPipeline
from engines.responsibility.pii_check.intercept_pipeline import InterceptPipelineError
from engines.responsibility.pii_check.pii_detector import PresidioPIIDetector
from engines.responsibility.pii_check.secret_detector import SecretDetector
from engines.responsibility.pii_check.policy.engine import PolicyEngine
from tests.pii_check.test_india_pii import AADHAAR, PAN, PASSPORT


class ControlledEmbeddingModel:
    """Synthetic vectors allow confidential-policy integration tests offline."""

    def encode(self, sentences, *, normalize_embeddings):
        vectors = []
        for sentence in sentences:
            text = sentence.casefold()
            if any(term in text for term in ("roadmap", "launch strategy", "unreleased", "employee-only")):
                vectors.append([1, 0, 0, 0, 0])
            elif any(term in text for term in ("financial", "revenue", "forecast", "acquisition")):
                vectors.append([0, 1, 0, 0, 0])
            elif any(term in text for term in ("customer", "client", "contract")):
                vectors.append([0, 0, 1, 0, 0])
            elif any(term in text for term in ("security", "vulnerability", "penetration")):
                vectors.append([0, 0, 0, 1, 0])
            elif any(term in text for term in ("attorney", "privileged", "legal counsel")):
                vectors.append([0, 0, 0, 0, 1])
            else:
                vectors.append([0, 0, 0, 0, 0])
        return vectors


@pytest.fixture(scope="module")
def pipeline() -> SimulatedInterceptPipeline:
    return SimulatedInterceptPipeline(
        pii_detector=PresidioPIIDetector(),
        secret_detector=SecretDetector(),
        confidential_detector=ContextualConfidentialDetector(model=ControlledEmbeddingModel()),
        policy_engine=PolicyEngine(),
    )


@pytest.mark.parametrize(
    ("text", "expected_types"),
    [
        ("Contact maria.fernandez@example.org or +1 415-555-2671.", {"EMAIL_ADDRESS", "PHONE_NUMBER"}),
        (f"My Aadhaar number is {AADHAAR}.", {"IN_AADHAAR"}),
        (f"PAN number {PAN}; passport number {PASSPORT}.", {"IN_PAN", "IN_PASSPORT"}),
    ],
)
def test_external_pii_is_redacted_without_raw_value_leakage(pipeline, text, expected_types) -> None:
    response = pipeline.intercept(SimulatedInterceptRequest(text=text))
    assert response.action_taken == "REDACT"
    assert set(response.evidence.pii_types) >= expected_types
    assert response.redacted_prompt is not None
    assert all(value not in response.redacted_prompt for value in (AADHAAR, PAN, PASSPORT))
    assert text not in str(response.evidence)


def test_safe_coding_prompt_is_allowed_end_to_end(pipeline) -> None:
    response = pipeline.intercept(SimulatedInterceptRequest(text="Explain how merge sort works."))
    assert response.action_taken == "ALLOW"
    assert response.risk_score == 0.0
    assert response.evidence.pii_detected is False
    assert response.redacted_prompt is None


def test_known_high_confidence_secret_is_blocked(pipeline) -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
    response = pipeline.intercept(SimulatedInterceptRequest(text=f"api_key={secret}"))
    assert response.action_taken == "BLOCK"
    assert response.evidence.secret_detected is True
    assert response.evidence.policy_rule_ids == ["intercept.known_secret"]
    assert secret not in str(response.evidence)
    assert response.redacted_prompt is None


def test_entropy_secret_with_context_is_escalated(pipeline) -> None:
    response = pipeline.intercept(
        SimulatedInterceptRequest(text='api_key = "A7kP9mQx2Ld8Rf4Nz6Vc1Ys"')
    )
    assert response.action_taken == "ESCALATE"
    assert response.evidence.policy_rule_ids == ["intercept.possible_secret"]


def test_confidential_strategy_is_escalated(pipeline) -> None:
    response = pipeline.intercept(
        SimulatedInterceptRequest(text="The unreleased product roadmap defines our launch strategy.")
    )
    assert response.action_taken == "ESCALATE"
    assert response.evidence.confidential_detected is True
    assert response.evidence.policy_rule_ids == ["intercept.confidential_information"]


def test_pii_and_secret_are_blocked(pipeline) -> None:
    secret = "AKIAIOSFODNN7EXAMPLE"
    response = pipeline.intercept(
        SimulatedInterceptRequest(text=f"Aadhaar {AADHAAR}; aws_access_key={secret}")
    )
    assert response.action_taken == "BLOCK"
    assert response.risk_score == 1.0
    assert response.evidence.pii_detected is True
    assert response.evidence.secret_detected is True


def test_unavailable_confidential_detector_stops_pipeline() -> None:
    class UnavailableConfidentialDetector:
        def scan(self, text, *, scan_target):
            from engines.responsibility.pii_check.confidential_detector import ConfidentialDetectorError
            raise ConfidentialDetectorError("unavailable")

    unavailable = SimulatedInterceptPipeline(
        pii_detector=PresidioPIIDetector(),
        secret_detector=SecretDetector(),
        confidential_detector=UnavailableConfidentialDetector(),
        policy_engine=PolicyEngine(),
    )
    with pytest.raises(InterceptPipelineError):
        unavailable.intercept(SimulatedInterceptRequest(text="Explain merge sort."))


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_intercept_endpoint_validates_input_and_returns_safe_result(monkeypatch, pipeline) -> None:
    monkeypatch.setattr("api.routes.responsibility.get_intercept_pipeline", lambda: pipeline)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        valid = await client.post("/responsibility/intercept", json={"text": f"Aadhaar {AADHAAR}"})
        missing = await client.post("/responsibility/intercept", json={})
        invalid_target = await client.post(
            "/responsibility/intercept", json={"text": "safe", "scan_target": "prompt"}
        )
    assert valid.status_code == 200
    assert valid.json()["action_taken"] == "REDACT"
    assert AADHAAR not in str(valid.json()["evidence"])
    assert missing.status_code == 422
    assert invalid_target.status_code == 422


@pytest.mark.anyio
async def test_intercept_preserves_detector_unavailable_503(monkeypatch) -> None:
    class UnavailablePipeline:
        def intercept(self, request):
            from engines.responsibility.pii_check.intercept_pipeline import InterceptPipelineError
            raise InterceptPipelineError("unavailable")

    monkeypatch.setattr("api.routes.responsibility.get_intercept_pipeline", lambda: UnavailablePipeline())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/responsibility/intercept", json={"text": "safe"})
    assert response.status_code == 503
    assert "safe" not in response.text
