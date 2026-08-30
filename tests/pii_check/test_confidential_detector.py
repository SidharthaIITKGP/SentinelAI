import pytest

from engines.responsibility.pii_check.confidential_detector import ContextualConfidentialDetector


class DeterministicEmbeddingModel:
    """Stable test embeddings whose scenario vectors do not depend on detector keywords."""

    def encode(self, sentences, *, normalize_embeddings):
        assert normalize_embeddings is True
        vectors = []
        vectors = []
        scenario_vectors = {
            "The launch note for Orion is employee-only.": [1.0, 0.0, 0.0, 0.0, 0.0],
            "The board pack estimates next quarter sales.": [0.0, 1.0, 0.0, 0.0, 0.0],
            "The client renewal terms are under review.": [0.0, 0.0, 1.0, 0.0, 0.0],
            "The audit identified a weakness in the production perimeter.": [0.0, 0.0, 0.0, 1.0, 0.0],
            "Counsel prepared the case assessment.": [0.0, 0.0, 0.0, 0.0, 1.0],
            "Explain binary search.": [0.0, 0.0, 0.0, 0.0, 0.0],
            "Near threshold.": [0.71, 0.0, 0.0, 0.0, 0.0],
        }
        reference_vectors = {
            "confidential internal product roadmap and unreleased features": [1.0, 0.0, 0.0, 0.0, 0.0],
            "internal project code name and launch strategy": [1.0, 0.0, 0.0, 0.0, 0.0],
            "employee-only engineering planning document": [1.0, 0.0, 0.0, 0.0, 0.0],
            "non-public quarterly financial results and revenue forecast": [0.0, 1.0, 0.0, 0.0, 0.0],
            "confidential merger acquisition valuation and earnings forecast": [0.0, 1.0, 0.0, 0.0, 0.0],
            "internal budget and sales forecast before public release": [0.0, 1.0, 0.0, 0.0, 0.0],
            "confidential customer account information and client contract terms": [0.0, 0.0, 1.0, 0.0, 0.0],
            "private customer usage data and account history": [0.0, 0.0, 1.0, 0.0, 0.0],
            "enterprise client pricing and renewal negotiation details": [0.0, 0.0, 1.0, 0.0, 0.0],
            "internal security architecture and vulnerability remediation details": [0.0, 0.0, 0.0, 1.0, 0.0],
            "production infrastructure access design and security incident report": [0.0, 0.0, 0.0, 1.0, 0.0],
            "unpublished penetration test findings and security weaknesses": [0.0, 0.0, 0.0, 1.0, 0.0],
            "attorney client privileged legal advice and litigation strategy": [0.0, 0.0, 0.0, 0.0, 1.0],
            "confidential legal counsel assessment and settlement discussion": [0.0, 0.0, 0.0, 0.0, 1.0],
            "privileged investigation findings prepared for legal counsel": [0.0, 0.0, 0.0, 0.0, 1.0],
        }
        for sentence in sentences:
            vectors.append(scenario_vectors.get(sentence, reference_vectors.get(sentence, [0.0] * 5)))
        return vectors


@pytest.fixture
def detector() -> ContextualConfidentialDetector:
    return ContextualConfidentialDetector(model=DeterministicEmbeddingModel())


def test_safe_text_has_no_confidential_information(detector: ContextualConfidentialDetector) -> None:
    result = detector.scan("Explain how binary search works.")
    assert result.detected is False
    assert result.findings == []
    assert result.risk_score == 0.0


def test_internal_roadmap_is_detected_without_source_text(detector: ContextualConfidentialDetector) -> None:
    source = "The launch note for Orion is employee-only."
    result = detector.scan(source)
    assert result.detected is True
    finding = result.findings[0]
    assert finding.category == "INTERNAL_PROJECT"
    assert finding.redacted_placeholder == "<CONFIDENTIAL_INFORMATION:INTERNAL_PROJECT>"
    assert source not in str(result.model_dump())
    assert 0.0 <= finding.score <= 1.0


def test_multiple_contextual_categories_are_detected(detector: ContextualConfidentialDetector) -> None:
    result = detector.scan(
        "The board pack estimates next quarter sales. The audit identified a weakness in the production perimeter."
    )
    categories = {finding.category for finding in result.findings}
    assert "FINANCIAL_INFORMATION" in categories
    assert "SECURITY_INFORMATION" in categories
    assert result.finding_count == 2


def test_anonymization_replaces_confidential_segment(detector: ContextualConfidentialDetector) -> None:
    source = "Counsel prepared the case assessment. Explain binary search."
    result, anonymized = detector.anonymize(source)
    assert result.detected is True
    assert "Counsel" not in anonymized
    assert "<CONFIDENTIAL_INFORMATION:LEGAL_PRIVILEGED>" in anonymized
    assert "Explain binary search." in anonymized


def test_empty_text_is_safe(detector: ContextualConfidentialDetector) -> None:
    result, anonymized = detector.anonymize("")
    assert result.detected is False
    assert anonymized == ""


def test_invalid_target_is_rejected(detector: ContextualConfidentialDetector) -> None:
    with pytest.raises(ValueError, match="scan_target"):
        detector.scan("internal roadmap", scan_target="invalid")


def test_below_threshold_embedding_is_not_flagged(detector: ContextualConfidentialDetector) -> None:
    result = detector.scan("Near threshold.")
    assert result.detected is False
