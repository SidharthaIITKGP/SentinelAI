import pytest

from engines.responsibility.pii_check.secret_detector import SecretDetector


@pytest.fixture
def detector() -> SecretDetector:
    return SecretDetector()


def test_safe_text_has_no_secrets(detector: SecretDetector) -> None:
    result = detector.scan("Explain binary search with a short example.")
    assert result.found is False
    assert result.findings == []
    assert result.risk_score == 0.0


def test_openai_key_is_detected_without_exposing_value(detector: SecretDetector) -> None:
    key = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
    result = detector.scan(f"OPENAI_API_KEY={key}")
    assert result.found is True
    finding = next(item for item in result.findings if item.secret_type == "OPENAI_API_KEY")
    assert finding.redacted_placeholder == "<OPENAI_API_KEY>"
    assert 0.0 <= finding.score <= 1.0
    assert key not in str(result.model_dump())


def test_multiple_secret_types_are_detected(detector: SecretDetector) -> None:
    aws_key = "AKIAIOSFODNN7EXAMPLE"
    github_token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    result = detector.scan(f"aws={aws_key} github={github_token}")
    types = {item.secret_type for item in result.findings}
    assert "AWS_ACCESS_KEY_ID" in types
    assert "GITHUB_TOKEN" in types
    assert result.secret_count == len(result.findings)
    assert result.risk_score == 1.0


def test_anonymization_preserves_labels_and_removes_values(detector: SecretDetector) -> None:
    key = "AKIAIOSFODNN7EXAMPLE"
    result, anonymized = detector.anonymize(f"aws_access_key={key}")
    assert result.found is True
    assert key not in anonymized
    assert anonymized == "aws_access_key=<AWS_ACCESS_KEY_ID>"


def test_generic_credential_assignment_is_detected(detector: SecretDetector) -> None:
    value = "correct-horse-battery-staple"
    result = detector.scan(f"password={value}")
    assert result.found is True
    assert result.findings[0].secret_type == "GENERIC_CREDENTIAL"
    assert result.findings[0].start == len("password=")


def test_near_match_and_short_generic_value_are_not_detected(detector: SecretDetector) -> None:
    result = detector.scan("The identifier is AKIAIOSFODNN7EXAMPL and token=short.")
    assert result.found is False


def test_specific_token_wins_over_generic_assignment(detector: SecretDetector) -> None:
    token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    result = detector.scan(f"token={token}")
    assert result.secret_count == 1
    assert result.findings[0].secret_type == "GITHUB_TOKEN"


def test_quoted_generic_credential_redacts_only_the_value(detector: SecretDetector) -> None:
    value = "correct-horse-battery-staple"
    _, anonymized = detector.anonymize(f'password="{value}"')
    assert anonymized == 'password="<GENERIC_CREDENTIAL>"'


def test_empty_text_is_safe(detector: SecretDetector) -> None:
    result, anonymized = detector.anonymize("")
    assert result.found is False
    assert anonymized == ""


def test_invalid_target_is_rejected(detector: SecretDetector) -> None:
    with pytest.raises(ValueError, match="scan_target"):
        detector.scan("token=abcdefgh", scan_target="invalid")
