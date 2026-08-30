import httpx
import pytest

from core.main import app
from engines.responsibility.pii_check.pii_detector import get_pii_detector
from tests.pii_check.test_pii_detector import synthetic_aadhaar


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_scan_endpoint_returns_safe_metadata() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/scan", json={"text": "Email alex@example.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["contains_pii"] is True
    assert body["findings"][0]["text"] == "<EMAIL_ADDRESS>"
    assert "alex@example.com" not in str(body["findings"])


@pytest.mark.anyio
async def test_anonymize_endpoint() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/anonymize", json={"text": "Email alex@example.com"})
    assert response.status_code == 200
    assert response.json()["anonymized_text"] == "Email <EMAIL_ADDRESS>"


@pytest.mark.anyio
async def test_missing_text_is_rejected_before_presidio() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/scan", json={})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_invalid_scan_target_is_rejected_before_presidio() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/scan", json={"text": "hello", "scan_target": "bad"})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_non_string_pii_text_is_rejected() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/scan", json={"text": 42})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_indian_pii_api_response_does_not_leak_raw_values() -> None:
    aadhaar = synthetic_aadhaar()
    pan = "ABCDE1234F"
    passport = "P1234567"
    source = f"Aadhaar {aadhaar}; PAN {pan}; passport number {passport}."
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/anonymize", json={"text": source})
    assert response.status_code == 200
    body = response.json()
    assert {item["entity_type"] for item in body["findings"]} >= {
        "IN_AADHAAR", "IN_PAN", "IN_PASSPORT"
    }
    assert all(value not in str(body["findings"]) for value in (aadhaar, pan, passport))
    assert all(value not in body["anonymized_text"] for value in (aadhaar, pan, passport))


@pytest.mark.anyio
async def test_secret_scan_endpoint_returns_safe_metadata() -> None:
    key = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/secrets/scan", json={"text": f"key={key}"})
    assert response.status_code == 200
    body = response.json()
    assert body["contains_secrets"] is True
    assert body["findings"][0]["secret_type"] == "OPENAI_API_KEY"
    assert key not in str(body)


@pytest.mark.anyio
async def test_secret_anonymize_endpoint() -> None:
    key = "AKIAIOSFODNN7EXAMPLE"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/secrets/anonymize", json={"text": f"aws_access_key={key}"})
    assert response.status_code == 200
    assert response.json()["anonymized_text"] == "aws_access_key=<AWS_ACCESS_KEY_ID>"


@pytest.mark.anyio
async def test_missing_secret_text_is_rejected() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/secrets/scan", json={})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_confidential_scan_endpoint_returns_safe_metadata(monkeypatch) -> None:
    from engines.responsibility.pii_check.confidential_detector import ContextualConfidentialDetector
    from tests.pii_check.test_confidential_detector import DeterministicEmbeddingModel

    detector = ContextualConfidentialDetector(model=DeterministicEmbeddingModel())
    monkeypatch.setattr("api.routes.responsibility.get_confidential_detector", lambda: detector)
    source = "The launch note for Orion is employee-only."
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/confidential/scan", json={"text": source})
    assert response.status_code == 200
    body = response.json()
    assert body["contains_confidential_information"] is True
    assert body["findings"][0]["category"] == "INTERNAL_PROJECT"
    assert source not in str(body)


@pytest.mark.anyio
async def test_confidential_anonymize_endpoint(monkeypatch) -> None:
    from engines.responsibility.pii_check.confidential_detector import ContextualConfidentialDetector
    from tests.pii_check.test_confidential_detector import DeterministicEmbeddingModel

    detector = ContextualConfidentialDetector(model=DeterministicEmbeddingModel())
    monkeypatch.setattr("api.routes.responsibility.get_confidential_detector", lambda: detector)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/responsibility/confidential/anonymize",
            json={"text": "The board pack estimates next quarter sales."},
        )
    assert response.status_code == 200
    assert response.json()["anonymized_text"] == "<CONFIDENTIAL_INFORMATION:FINANCIAL_INFORMATION>"


@pytest.mark.anyio
async def test_missing_confidential_text_is_rejected() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/responsibility/confidential/scan", json={})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_policy_endpoint_uses_safe_aggregate_inputs() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/responsibility/policy/evaluate",
            json={
                "use_case": "finance_tool",
                "risk_score": 0.2,
                "pii_detected": True,
                "proposed_action": "REDACT",
            },
        )
    assert response.status_code == 200
    assert response.json() == {
        "approved": True,
        "final_action": "REDACT",
        "reason": "Sensitive-data detector signal requires the configured protective action.",
        "policy_file": "engines/responsibility/pii_check/policy/thresholds.yaml",
        "threshold_applied": 0.0,
        "policy_rule_ids": ["use_case.protective_signal"],
    }
