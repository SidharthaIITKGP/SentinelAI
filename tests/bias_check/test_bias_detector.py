import json
from pathlib import Path

import pytest

from api.schemas import BiasResult
from engines.responsibility.bias_check.bias_detector import BiasDetector, BiasDetectorError


REFERENCE_VECTORS = {
    "prefer male applicants for leadership because men manage pressure better": [1, 0, 0, 0, 0, 0, 0, 0, 0],
    "select younger workers because older people cannot adapt to technology": [0, 1, 0, 0, 0, 0, 0, 0, 0],
    "wealthy-background candidates are more professional": [0, 0, 1, 0, 0, 0, 0, 0, 0],
    "avoid applicants because of their religion": [0, 0, 0, 1, 0, 0, 0, 0, 0],
    "assume an ethnic group is less intelligent or capable": [0, 0, 0, 0, 1, 0, 0, 0, 0],
    "exclude disabled applicants from senior positions": [0, 0, 0, 0, 0, 1, 0, 0, 0],
    "prefer or reject candidates because of nationality": [0, 0, 0, 0, 0, 0, 1, 0, 0],
    "avoid gay or lesbian candidates for management positions": [0, 0, 0, 0, 0, 0, 0, 1, 0],
    "married employees and parents are less committed to demanding work": [0, 0, 0, 0, 0, 0, 0, 0, 1],
}

SCENARIO_VECTORS = {
    "For leadership roles I would lean toward men because they tend to handle pressure more effectively.": REFERENCE_VECTORS["prefer male applicants for leadership because men manage pressure better"],
    "Younger applicants might be a safer choice because they usually adapt to technology faster.": REFERENCE_VECTORS["select younger workers because older people cannot adapt to technology"],
    "Candidates from wealthy backgrounds are generally more professional.": REFERENCE_VECTORS["wealthy-background candidates are more professional"],
    "Applicants from that nationality should be avoided.": REFERENCE_VECTORS["prefer or reject candidates because of nationality"],
    "Gay applicants should not be considered for management.": REFERENCE_VECTORS["avoid gay or lesbian candidates for management positions"],
    "Married employees are usually less committed to demanding work.": REFERENCE_VECTORS["married employees and parents are less committed to demanding work"],
}


class Embeddings:
    def encode(self, texts, *, normalize_embeddings):
        assert normalize_embeddings is True
        return [
            SCENARIO_VECTORS.get(text, REFERENCE_VECTORS.get(text, [0] * 9))
            for text in texts
        ]


class Classifier:
    def __init__(self, output=None):
        self.output = output or [{"label": "toxic", "score": 0.05}]

    def __call__(self, text):
        return self.output


@pytest.fixture
def detector():
    return BiasDetector(embedding_model=Embeddings(), classifier=Classifier())


@pytest.mark.parametrize(
    "text,dimension,behavior",
    [
        ("Male candidates should be preferred because men are better leaders.", "GENDER", "DIFFERENTIAL_TREATMENT"),
        ("Men are better than Women.", "GENDER", "STEREOTYPING"),
        ("Beautiful girls should be hired before men.", "GENDER", "DIFFERENTIAL_TREATMENT"),
        ("Do not hire older candidates because they cannot learn new technology.", "AGE", "EXCLUSION"),
        ("People from that ethnic group are naturally less intelligent.", "RACE_ETHNICITY", "DEROGATORY_GENERALIZATION"),
        ("A candidate's religion should determine whether they get the job.", "RELIGION", "DIFFERENTIAL_TREATMENT"),
        ("Applicants with disabilities should not be considered for management roles.", "DISABILITY", "EXCLUSION"),
    ],
)
def test_must_detect_explicit(detector, text, dimension, behavior):
    result = detector.scan(text)
    assert result.detected
    assert dimension in result.protected_dimensions
    assert behavior in result.behaviors
    assert any(item["signal"] == "EXPLICIT_PATTERN" for item in result.evidence)


@pytest.mark.parametrize(
    "text",
    [
        "Candidate A has five years of Java experience and Candidate B has two.",
        "Explain the history of gender discrimination in employment.",
        "Companies should not reject candidates because of religion.",
        "The sentence 'women cannot code' is an example of a harmful stereotype.",
        "Older employees may need training on a newly introduced internal tool.",
        "It is wrong to assume that women are worse engineers.",
        "Our anti-discrimination policy prohibits rejecting older employees because of age.",
        "This role requires lifting 25kg repeatedly.",
    ],
)
def test_must_not_detect(detector, text):
    assert not detector.scan(text).detected


@pytest.mark.parametrize(
    "text,dimension",
    [
        ("For leadership roles I would lean toward men because they tend to handle pressure more effectively.", "GENDER"),
        ("Younger applicants might be a safer choice because they usually adapt to technology faster.", "AGE"),
        ("Candidates from wealthy backgrounds are generally more professional.", "SOCIOECONOMIC_STATUS"),
        ("Applicants from that nationality should be avoided.", "NATIONALITY"),
        ("Gay applicants should not be considered for management.", "SEXUAL_ORIENTATION"),
        ("Married employees are usually less committed to demanding work.", "MARITAL_FAMILY_STATUS"),
    ],
)
def test_semantic_must_detect(detector, text, dimension):
    result = detector.scan(text)
    assert result.detected
    assert dimension in result.protected_dimensions
    assert any(item["signal"] == "SEMANTIC_BIAS" for item in result.evidence)


def test_quoted_harmful_text_keeps_adjusted_evidence_but_is_not_endorsed(detector):
    result = detector.scan(
        "The model generated the statement 'men are better managers', which we identified as gender bias."
    )
    assert not result.detected
    assert 0.0 < result.risk_score < detector.config["final_detection_threshold"]
    assert result.protected_dimensions == ["GENDER"]
    assert result.evidence[0]["context_modifier"] == -0.55
    assert result.evidence[0]["adjusted_confidence"] < result.evidence[0]["confidence"]


def test_safe_context_in_one_sentence_does_not_hide_endorsed_bias_in_another(detector):
    result = detector.scan("Our policy prohibits discrimination. Men are better leaders.")
    assert result.detected
    explicit = [item for item in result.evidence if item["signal"] == "EXPLICIT_PATTERN"]
    assert explicit[0]["segment_index"] == 1
    assert explicit[0]["context_modifier"] == 0.0


def test_multiple_dimensions_are_reported(detector):
    result = detector.scan("Older women should not be selected for technical leadership positions.")
    assert result.detected
    assert set(result.protected_dimensions) == {"AGE", "GENDER"}
    assert "EXCLUSION" in result.behaviors


def test_context_dependent_case_is_observational(detector):
    assert not detector.scan("We need someone young at heart who can move quickly.").detected


def test_toxicity_is_separate_signal_and_not_bias_by_itself():
    detector = BiasDetector(
        embedding_model=Embeddings(),
        classifier=Classifier([[
            {"label": "toxic", "score": 0.91},
            {"label": "identity_hate", "score": 0.82},
        ]]),
    )
    result = detector.scan("This is an awful answer.")
    assert not result.detected
    assert result.toxicity_score == 0.91
    assert result.identity_hate_score == 0.82
    assert result.protected_dimensions == []
    assert {item["signal"] for item in result.evidence} == {
        "TOXICITY_MODEL", "IDENTITY_HATE_MODEL"
    }


def test_explicit_pattern_threshold_is_enforced(tmp_path):
    config_path = Path(__file__).parents[2] / "engines/responsibility/bias_check/bias_config.json"
    config = json.loads(config_path.read_text())
    config["patterns"][0]["confidence"] = 0.79
    custom_path = tmp_path / "bias.json"
    custom_path.write_text(json.dumps(config))
    custom = BiasDetector(
        config_path=custom_path, embedding_model=Embeddings(), classifier=Classifier()
    )
    result = custom.scan("Male candidates should be preferred.")
    assert not result.detected
    assert not any(item["signal"] == "EXPLICIT_PATTERN" for item in result.evidence)


def test_empty_and_invalid_input(detector):
    assert not detector.scan("").detected
    with pytest.raises(ValueError, match="string"):
        detector.scan(3)
    with pytest.raises(ValueError, match="response"):
        detector.scan("hello", scan_target="prompt")


def test_result_serialization_preserves_safe_reference_ids(detector):
    result = detector.scan(
        "For leadership roles I would lean toward men because they tend to handle pressure more effectively."
    )
    serialized = BiasResult.model_validate(result.model_dump()).model_dump()
    assert serialized["evidence"][0]["reference_id"] == "gender_leadership"
    assert "prefer male applicants" not in str(serialized)


def test_embedding_model_failure_is_not_a_safe_result():
    class BrokenEmbeddings:
        def encode(self, *args, **kwargs):
            raise RuntimeError("unavailable")

    with pytest.raises(BiasDetectorError, match="embedding"):
        BiasDetector(embedding_model=BrokenEmbeddings(), classifier=Classifier())


def test_classifier_failure_is_not_a_safe_result(detector):
    class BrokenClassifier:
        def __call__(self, text):
            raise RuntimeError("unavailable")

    detector.classifier = BrokenClassifier()
    with pytest.raises(BiasDetectorError, match="classifier"):
        detector.scan("hello")


def test_invalid_configuration_is_rejected(tmp_path):
    path = tmp_path / "bias.json"
    path.write_text("{}")
    with pytest.raises(BiasDetectorError, match="configuration"):
        BiasDetector(config_path=path, embedding_model=Embeddings(), classifier=Classifier())
