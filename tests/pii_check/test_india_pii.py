"""Independent India-specific PII tests using synthetic identifiers only."""

import pytest

from engines.responsibility.pii_check.pii_detector import PresidioPIIDetector


_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6), (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4), (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2), (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def synthetic_aadhaar() -> str:
    """Generate a non-issued, checksum-valid test identifier."""
    base = "23456789012"
    checksum = 0
    for index, digit in enumerate(reversed(base)):
        checksum = _D[checksum][_P[(index + 1) % 8][int(digit)]]
    return base + str(_INV[checksum])


AADHAAR = synthetic_aadhaar()
PAN = "ABCDE1234F"
PASSPORT = "P1234567"


@pytest.fixture(scope="module")
def detector() -> PresidioPIIDetector:
    return PresidioPIIDetector()


def entity_types(result) -> set[str]:
    return {entity.entity_type for entity in result.entities}


# MUST_DETECT
@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        (f"My Aadhaar number is {AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}", "IN_AADHAAR"),
        (f"My Aadhaar number is {AADHAAR}", "IN_AADHAAR"),
        (f"PAN number: {PAN}", "IN_PAN"),
        (f"PAN number: {PAN.lower()}", "IN_PAN"),
        (f"Indian passport number is {PASSPORT}", "IN_PASSPORT"),
        (f'{{"pan": "{PAN}", "status": "active"}}', "IN_PAN"),
        (f"INFO customer aadhaar={AADHAAR}", "IN_AADHAAR"),
        ("Contact maria.fernandez@example.org", "EMAIL_ADDRESS"),
        ("Call +1 415-555-2671", "PHONE_NUMBER"),
    ],
)
def test_must_detect(detector: PresidioPIIDetector, text: str, expected_type: str) -> None:
    assert expected_type in entity_types(detector.scan(text))


# MUST_NOT_DETECT
@pytest.mark.parametrize(
    ("text", "forbidden_type"),
    [
        (f"Aadhaar {AADHAAR[:-1]}{(int(AADHAAR[-1]) + 1) % 10}", "IN_AADHAAR"),
        ("Order number 123456789012 has been shipped.", "IN_AADHAAR"),
        ("PAN: ABC1234567", "IN_PAN"),
        ("PAN: ABCDE12X4F", "IN_PAN"),
        ("PAN: 12345ABCDZ", "IN_PAN"),
        (f"Transaction reference {PASSPORT}", "IN_PASSPORT"),
        ("Passport number: PP1234567", "IN_PASSPORT"),
        ("The deployment uses port 8080 and version 12.34.56.", "IN_AADHAAR"),
        ("The deployment uses port 8080 and version 12.34.56.", "IN_PAN"),
        ("The deployment uses port 8080 and version 12.34.56.", "IN_PASSPORT"),
    ],
)
def test_must_not_detect(detector: PresidioPIIDetector, text: str, forbidden_type: str) -> None:
    assert forbidden_type not in entity_types(detector.scan(text))


def test_safe_text_has_no_pii(detector: PresidioPIIDetector) -> None:
    assert detector.scan("Explain how merge sort works.").found is False


# CONTEXT_DEPENDENT / observational
def test_pan_like_build_identifier_is_never_high_confidence_without_pan_context(
    detector: PresidioPIIDetector,
) -> None:
    result = detector.scan(f"Build ID {PAN} completed successfully.")
    findings = [entity for entity in result.entities if entity.entity_type == "IN_PAN"]
    assert not findings or findings[0].score <= 0.75


def test_context_negation_does_not_disable_pan_detection(detector: PresidioPIIDetector) -> None:
    result = detector.scan(f"This is not a PAN number: {PAN}")
    assert "IN_PAN" in entity_types(result)


@pytest.mark.parametrize(
    ("source", "placeholder", "raw_value"),
    [
        (f"Aadhaar number: {AADHAAR}", "<IN_AADHAAR>", AADHAAR),
        (f"PAN number: {PAN}", "<IN_PAN>", PAN),
        (f"Passport number: {PASSPORT}", "<IN_PASSPORT>", PASSPORT),
    ],
)
def test_individual_anonymization_and_no_leakage(
    detector: PresidioPIIDetector, source: str, placeholder: str, raw_value: str
) -> None:
    result, anonymized = detector.anonymize(source)
    assert raw_value not in anonymized
    assert placeholder in anonymized
    for entity in result.entities:
        if entity.entity_type in {"IN_AADHAAR", "IN_PAN", "IN_PASSPORT"}:
            assert entity.text == entity.redacted_placeholder
            assert entity.text.startswith("<IN_")
            assert raw_value not in entity.text


def test_multiple_indian_identifiers_anonymize_without_leakage(detector: PresidioPIIDetector) -> None:
    source = f"Aadhaar {AADHAAR}, PAN {PAN}, Indian passport number {PASSPORT}."
    result, anonymized = detector.anonymize(source)
    assert {"IN_AADHAAR", "IN_PAN", "IN_PASSPORT"} <= entity_types(result)
    assert all(value not in anonymized for value in (AADHAAR, PAN, PASSPORT))
    assert all(token in anonymized for token in ("<IN_AADHAAR>", "<IN_PAN>", "<IN_PASSPORT>"))


def test_no_detected_indian_entity_exposes_its_raw_value(detector: PresidioPIIDetector) -> None:
    source = f"Aadhaar {AADHAAR}, PAN {PAN}, passport number {PASSPORT}."
    result = detector.scan(source)
    raw_values = (AADHAAR, PAN, PASSPORT)
    indian_entities = [entity for entity in result.entities if entity.entity_type.startswith("IN_")]
    assert len(indian_entities) == 3
    for entity in indian_entities:
        assert entity.text == entity.redacted_placeholder
        assert all(value not in entity.text for value in raw_values)
