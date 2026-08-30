"""Phase 3 upgrade acceptance tests: taxonomy, context, entropy, and hybrid evidence."""

import json

import pytest

from engines.responsibility.pii_check.confidential_detector import ContextualConfidentialDetector
from engines.responsibility.pii_check.phase3_config import load_phase3_config
from engines.responsibility.pii_check.pii_detector import PresidioPIIDetector
from engines.responsibility.pii_check.secret_detector import SecretDetector
from tests.pii_check.test_india_pii import AADHAAR, PAN, PASSPORT


class HybridEmbeddingModel:
    """Controlled vectors exercise hybrid scoring without downloading a model."""

    def encode(self, sentences, *, normalize_embeddings):
        vectors = []
        for sentence in sentences:
            text = sentence.casefold()
            if "internal product roadmap" in text or "project code name" in text or "employee-only engineering" in text:
                vectors.append([1, 0, 0, 0, 0])
            elif "quarterly financial" in text or "merger acquisition" in text or "sales forecast" in text:
                vectors.append([0, 1, 0, 0, 0])
            elif "customer account" in text or "customer usage" in text or "client pricing" in text:
                vectors.append([0, 0, 1, 0, 0])
            elif "security architecture" in text or "production infrastructure" in text or "penetration test" in text:
                vectors.append([0, 0, 0, 1, 0])
            elif "attorney client" in text or "legal counsel" in text or "privileged investigation" in text:
                vectors.append([0, 0, 0, 0, 1])
            elif "pricing strategy" in text or "acquisition target" in text:
                vectors.append([0, 1, 0, 0, 0])
            elif "contract renewal prices" in text:
                vectors.append([0, 0, 1, 0, 0])
            elif "generic contract template" in text:
                vectors.append([0, 0, 0.8, 0, 0])
            else:
                vectors.append([0, 0, 0, 0, 0])
        return vectors


@pytest.fixture(scope="module")
def pii_detector() -> PresidioPIIDetector:
    return PresidioPIIDetector()


@pytest.fixture
def secret_detector() -> SecretDetector:
    return SecretDetector()


@pytest.fixture
def confidential_detector() -> ContextualConfidentialDetector:
    return ContextualConfidentialDetector(model=HybridEmbeddingModel())


def test_configured_alias_and_project_are_detected_with_safe_evidence(pii_detector) -> None:
    result = pii_detector.scan("MSFT announced earnings. Project Orion launch is delayed.")
    entities = {entity.entity_type: entity for entity in result.entities}
    assert entities["DOMAIN_ORGANIZATION"].detection_method == "ALIAS"
    assert entities["DOMAIN_PROJECT"].detection_method in {"DICTIONARY", "ALIAS"}
    assert entities["DOMAIN_ORGANIZATION"].signals == ["taxonomy_match"]


def test_model_ner_and_configured_uncommon_name_fallback(pii_detector) -> None:
    model_result = pii_detector.scan("John Smith joined the meeting.")
    assert "PERSON" in {entity.entity_type for entity in model_result.entities}
    dictionary_result = pii_detector.scan("Dr. Zorven Kahl submitted the report.")
    people = [entity for entity in dictionary_result.entities if entity.entity_type == "PERSON"]
    assert people
    assert any(entity.detection_method in {"DICTIONARY", "ALIAS", "MODEL_NER"} for entity in people)
    assert all(entity.text == "<PERSON>" for entity in people)


def test_organization_business_context_and_lowercase_fruit_context(pii_detector) -> None:
    business = pii_detector.scan("Apple released a device.")
    assert "ORGANIZATION" in {entity.entity_type for entity in business.entities}
    fruit = pii_detector.scan("I ate an apple.")
    assert "ORGANIZATION" not in {entity.entity_type for entity in fruit.entities}


def test_custom_taxonomy_path_is_loaded_without_detector_hardcoding(tmp_path) -> None:
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text(json.dumps({
        "organizations": {"Synthetic Supplier": ["SYN-SUP"]},
        "projects": {"Synthetic Project": ["Project Nebula"]},
        "domain_terms": {}, "semantic": {},
    }))
    detector = PresidioPIIDetector(load_phase3_config(taxonomy))
    types = {entity.entity_type for entity in detector.scan("SYN-SUP supports Project Nebula.").entities}
    assert {"DOMAIN_ORGANIZATION", "DOMAIN_PROJECT"} <= types


def test_pan_context_changes_confidence_without_disabling_detection(pii_detector) -> None:
    contextual = next(entity for entity in pii_detector.scan(f"PAN number {PAN}").entities if entity.entity_type == "IN_PAN")
    build = [entity for entity in pii_detector.scan(f"Build ID {PAN} completed.").entities if entity.entity_type == "IN_PAN"]
    assert contextual.score == 1.0
    assert not build or build[0].score <= 0.75


@pytest.mark.parametrize(
    ("text", "expected_type", "expected_method"),
    [
        ('api_key = "A7kP9mQx2Ld8Rf4Nz6Vc1Ys"', "POSSIBLE_SECRET", "ENTROPY_PLUS_CONTEXT"),
        ('password = "fK8qP2LmR9VzX4Nc"', "POSSIBLE_SECRET", "ENTROPY_PLUS_CONTEXT"),
        ('Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vIn0.signaturepart123', "JSON_WEB_TOKEN", "KNOWN_PATTERN_SECRET"),
        ('const API_KEY = "A7kP9mQx2Ld8Rf4Nz6Vc1Ys";', "POSSIBLE_SECRET", "ENTROPY_PLUS_CONTEXT"),
    ],
)
def test_controlled_entropy_and_known_secret_detection(secret_detector, text, expected_type, expected_method) -> None:
    finding = next(item for item in secret_detector.scan(text).findings if item.secret_type == expected_type)
    assert finding.detection_method == expected_method
    assert finding.signals


@pytest.mark.parametrize(
    "text",
    [
        'sha256 = "9f86d081884c7d659a2feaa0c55ad015"',
        "request_id = A7kP9mQx2Ld8Rf4Nz6Vc1Ys",
        "Build artifact 8b17c92d12af completed successfully.",
    ],
)
def test_entropy_rejects_harmless_or_context_free_values(secret_detector, text) -> None:
    assert "POSSIBLE_SECRET" not in {item.secret_type for item in secret_detector.scan(text).findings}


def test_entropy_allowlist_prevents_possible_secret(secret_detector) -> None:
    result = secret_detector.scan('api_key = "TEST_VALUE_ALLOWED_12345"')
    assert "POSSIBLE_SECRET" not in {item.secret_type for item in result.findings}


@pytest.mark.parametrize(
    ("text", "expected_category"),
    [
        ("Our unreleased Q4 pricing strategy includes a 14% enterprise increase.", "FINANCIAL_INFORMATION"),
        ("The internal acquisition target is Project Orion.", "FINANCIAL_INFORMATION"),
        ("Customer contract renewal prices are in the attached draft.", "CUSTOMER_INFORMATION"),
    ],
)
def test_hybrid_semantic_must_detect(confidential_detector, text, expected_category) -> None:
    finding = confidential_detector.scan(text).findings[0]
    assert finding.category == expected_category
    assert finding.detection_method == "HYBRID_SEMANTIC"
    assert "semantic_similarity" in finding.signals


@pytest.mark.parametrize(
    "text",
    ["Explain the concept of pricing strategy.", "What is an acquisition in business?", "Write a generic contract template."],
)
def test_hybrid_semantic_negative_context_is_not_confidential(confidential_detector, text) -> None:
    assert confidential_detector.scan(text).detected is False


def test_mixed_pii_and_entropy_secret_detectors_preserve_safe_metadata(pii_detector, secret_detector) -> None:
    text = 'The API key is "A7kP9mQx2Ld8Rf4Nz6Vc1Ys" and the owner is john@example.com.'
    pii = pii_detector.scan(text)
    secret = secret_detector.scan(text)
    assert "EMAIL_ADDRESS" in {entity.entity_type for entity in pii.entities}
    assert "POSSIBLE_SECRET" in {finding.secret_type for finding in secret.findings}
    assert "A7kP9mQx2Ld8Rf4Nz6Vc1Ys" not in str(secret.model_dump())


def test_safe_text_regression_across_detectors(pii_detector, secret_detector, confidential_detector) -> None:
    text = "Explain binary search and merge sort."
    assert pii_detector.scan(text).found is False
    assert secret_detector.scan(text).found is False
    assert confidential_detector.scan(text).detected is False


def test_existing_indian_pii_remains_detected(pii_detector) -> None:
    result = pii_detector.scan(f"Aadhaar {AADHAAR}, PAN {PAN}, passport number {PASSPORT}")
    assert {"IN_AADHAAR", "IN_PAN", "IN_PASSPORT"} <= {entity.entity_type for entity in result.entities}
