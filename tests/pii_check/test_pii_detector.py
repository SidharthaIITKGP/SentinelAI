import pytest

from engines.responsibility.pii_check.pii_detector import PresidioPIIDetector


_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6), (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4), (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2), (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def synthetic_aadhaar() -> str:
    """Generate a checksum-valid synthetic Aadhaar solely for tests."""
    base = "23456789012"
    checksum = 0
    for index, digit in enumerate(reversed(base)):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[(index + 1) % 8][int(digit)]]
    return base + str(_VERHOEFF_INV[checksum])


@pytest.fixture(scope="module")
def detector() -> PresidioPIIDetector:
    return PresidioPIIDetector()


def test_safe_text_has_no_pii(detector: PresidioPIIDetector) -> None:
    result = detector.scan("Explain how binary search works.")
    assert result.found is False
    assert result.entities == []
    assert result.risk_score == 0.0


def test_email_is_detected_without_leaking_value(detector: PresidioPIIDetector) -> None:
    result = detector.scan("My email is alex@example.com")
    assert result.found is True
    entity = next(entity for entity in result.entities if entity.entity_type == "EMAIL_ADDRESS")
    assert entity.text == "<EMAIL_ADDRESS>"
    assert entity.redacted_placeholder == "<EMAIL_ADDRESS>"
    assert 0.0 <= entity.score <= 1.0


def test_multiple_entities_are_detected(detector: PresidioPIIDetector) -> None:
    result = detector.scan("John Smith can be reached at john@example.com or +1 202-555-0198.")
    types = {entity.entity_type for entity in result.entities}
    assert "EMAIL_ADDRESS" in types
    assert "PHONE_NUMBER" in types
    assert result.entity_count == len(result.entities)


def test_anonymization_uses_typed_placeholders(detector: PresidioPIIDetector) -> None:
    result, anonymized = detector.anonymize("Contact alex@example.com on +1 202-555-0198")
    assert result.found is True
    assert "alex@example.com" not in anonymized
    assert "<EMAIL_ADDRESS>" in anonymized
    assert "<PHONE_NUMBER>" in anonymized


def test_credit_card_and_ip_address_are_detected(detector: PresidioPIIDetector) -> None:
    result = detector.scan("Card 4111-1111-1111-1111 was used from 203.0.113.10.")
    types = {entity.entity_type for entity in result.entities}
    assert "CREDIT_CARD" in types
    assert "IP_ADDRESS" in types
    assert "CREDIT_CARD" in result.high_risk_entities


def test_plain_numeric_text_is_not_treated_as_a_credit_card(detector: PresidioPIIDetector) -> None:
    result = detector.scan("The quarterly unit count was 1234567890123456.")
    assert "CREDIT_CARD" not in {entity.entity_type for entity in result.entities}


def test_checksum_valid_synthetic_aadhaar_is_detected_safely(detector: PresidioPIIDetector) -> None:
    aadhaar = synthetic_aadhaar()
    result = detector.scan(f"Aadhaar number: {aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:]}")
    entity = next(item for item in result.entities if item.entity_type == "IN_AADHAAR")
    assert entity.text == "<IN_AADHAAR>"
    assert entity.redacted_placeholder == "<IN_AADHAAR>"
    assert aadhaar not in str(result.model_dump())
    assert "IN_AADHAAR" in result.high_risk_entities


def test_checksum_invalid_aadhaar_is_rejected(detector: PresidioPIIDetector) -> None:
    aadhaar = synthetic_aadhaar()
    invalid = aadhaar[:-1] + str((int(aadhaar[-1]) + 1) % 10)
    result = detector.scan(f"Aadhaar: {invalid}")
    assert "IN_AADHAAR" not in {item.entity_type for item in result.entities}


def test_pan_requires_exact_structure(detector: PresidioPIIDetector) -> None:
    result = detector.scan("PAN / Permanent Account Number: ABCDE1234F")
    assert "IN_PAN" in {item.entity_type for item in result.entities}
    invalid = detector.scan("PAN: ABCD1234F and ABCDE12X4F")
    assert "IN_PAN" not in {item.entity_type for item in invalid.entities}


def test_passport_requires_context_and_format(detector: PresidioPIIDetector) -> None:
    detected = detector.scan("Passport number: P1234567")
    assert "IN_PASSPORT" in {item.entity_type for item in detected.entities}
    no_context = detector.scan("Reference P1234567 was entered.")
    assert "IN_PASSPORT" not in {item.entity_type for item in no_context.entities}
    invalid_format = detector.scan("Passport number: PP1234567")
    assert "IN_PASSPORT" not in {item.entity_type for item in invalid_format.entities}


def test_indian_identifiers_mix_with_existing_pii_and_anonymize(detector: PresidioPIIDetector) -> None:
    aadhaar = synthetic_aadhaar()
    source = (
        f"Email test@example.com, Aadhaar {aadhaar}, PAN ABCDE1234F, "
        "passport number P1234567."
    )
    result, anonymized = detector.anonymize(source)
    types = {item.entity_type for item in result.entities}
    assert {"EMAIL_ADDRESS", "IN_AADHAAR", "IN_PAN", "IN_PASSPORT"} <= types
    assert aadhaar not in anonymized
    assert "ABCDE1234F" not in anonymized
    assert "P1234567" not in anonymized
    assert "<IN_AADHAAR>" in anonymized
    assert "<IN_PAN>" in anonymized
    assert "<IN_PASSPORT>" in anonymized


def test_empty_text_is_safe(detector: PresidioPIIDetector) -> None:
    result, anonymized = detector.anonymize("")
    assert result.found is False
    assert anonymized == ""


def test_invalid_target_is_rejected(detector: PresidioPIIDetector) -> None:
    with pytest.raises(ValueError, match="scan_target"):
        detector.scan("hello", scan_target="invalid")
