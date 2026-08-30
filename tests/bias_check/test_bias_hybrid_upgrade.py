import json
from pathlib import Path

import pytest

from engines.responsibility.bias_check.bias_detector import BiasDetector, BiasDetectorError


CONFIG = json.loads(
    (Path(__file__).parents[2] / "engines/responsibility/bias_check/bias_config.json").read_text()
)
DIMENSIONS = sorted(CONFIG["fairness_trigger"]["protected_group_terms"])
DIMENSION_INDEX = {dimension: index for index, dimension in enumerate(DIMENSIONS)}
REFERENCE_DIMENSIONS = {
    item["text"]: item["dimension"] for item in CONFIG["semantic_references"]
}
SEMANTIC_SCENARIOS = {
    "Male candidates should receive preference for leadership roles.": "GENDER",
    "Young applicants should be selected before older applicants.": "AGE",
    "Applicants from wealthy families are generally better employees.": "SOCIOECONOMIC_STATUS",
    "Candidates from that religion should not be hired.": "RELIGION",
}


class UpgradeEmbeddings:
    def encode(self, texts, *, normalize_embeddings):
        assert normalize_embeddings is True
        vectors = []
        for text in texts:
            vector = [0.0] * len(DIMENSIONS)
            dimension = REFERENCE_DIMENSIONS.get(text) or SEMANTIC_SCENARIOS.get(text)
            if dimension:
                vector[DIMENSION_INDEX[dimension]] = 1.0
            vectors.append(vector)
        return vectors


class LowToxicityClassifier:
    def __call__(self, text):
        return [[
            {"label": "toxic", "score": 0.01},
            {"label": "identity_hate", "score": 0.001},
        ]]


class HighToxicityClassifier:
    def __call__(self, text):
        return [[
            {"label": "toxic", "score": 0.99},
            {"label": "identity_hate", "score": 0.01},
        ]]


class MockJudge:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = 0

    def judge(self, text, *, candidate_dimensions, evidence):
        self.calls += 1
        if self.error:
            raise self.error
        return self.output


@pytest.fixture
def detector():
    return BiasDetector(
        embedding_model=UpgradeEmbeddings(),
        classifier=LowToxicityClassifier(),
    )


@pytest.mark.parametrize(
    "text,dimension",
    [
        ("Beautiful girls should be hired before anyone else.", "GENDER"),
        ("Male candidates should receive preference for leadership roles.", "GENDER"),
        ("Young applicants should be selected before older applicants.", "AGE"),
        ("Applicants from wealthy families are generally better employees.", "SOCIOECONOMIC_STATUS"),
        ("Candidates from that religion should not be hired.", "RELIGION"),
    ],
)
def test_upgrade_must_detect(detector, text, dimension):
    result = detector.scan(text)
    assert result.detected
    assert dimension in result.protected_dimensions
    assert any(item["signal"] == "FAIRNESS_TRIGGER" for item in result.evidence)


@pytest.mark.parametrize(
    "text",
    [
        "Women should be hired based on qualifications and experience.",
        "Candidates should be evaluated regardless of gender.",
        "Do not reject applicants because of religion.",
        "The statement 'women are worse engineers' is a harmful stereotype.",
        "Our policy prohibits age discrimination.",
        "Candidate A has five years of experience and Candidate B has two.",
    ],
)
def test_upgrade_must_not_detect(detector, text):
    assert not detector.scan(text).detected


def test_low_toxicity_does_not_hide_clear_bias(detector):
    result = detector.scan("Beautiful girls should be hired before anyone else.")
    assert result.toxicity_score == 0.01
    assert result.detected
    assert result.risk_score >= 0.95


def test_high_toxicity_without_protected_class_is_not_bias():
    detector = BiasDetector(
        embedding_model=UpgradeEmbeddings(),
        classifier=HighToxicityClassifier(),
    )
    result = detector.scan("You are an absolutely disgusting idiot.")
    assert not result.detected
    assert result.toxicity_score == 0.99
    assert result.risk_score == 0.0
    assert any(item["signal"] == "TOXICITY_MODEL" for item in result.evidence)


def test_fairness_trigger_can_fire_while_final_result_is_safe(detector):
    result = detector.scan(
        "Women should be hired based on qualifications and experience."
    )
    assert not result.detected
    assert any(item["signal"] == "FAIRNESS_TRIGGER" for item in result.evidence)
    assert not any(
        item["signal"] in {"EXPLICIT_PATTERN", "SEMANTIC_BIAS"}
        for item in result.evidence
    )


def test_llm_judge_can_establish_bias_for_low_score_blind_spot():
    judge = MockJudge(
        {
            "endorses_bias": True,
            "protected_dimensions": ["GENDER"],
            "behaviors": ["DIFFERENTIAL_TREATMENT"],
            "confidence": 0.92,
        }
    )
    detector = BiasDetector(
        embedding_model=UpgradeEmbeddings(),
        classifier=LowToxicityClassifier(),
        llm_judge=judge,
    )
    result = detector.scan("Female applicants should be hired based on appearance.")
    assert judge.calls == 1
    assert result.detected
    assert result.risk_score == 0.92
    assert result.detection_method == "HYBRID_LLM"
    assert "GENDER" in result.protected_dimensions


def test_llm_judge_can_return_safe_for_fairness_trigger():
    judge = MockJudge(
        {
            "endorses_bias": False,
            "protected_dimensions": [],
            "behaviors": [],
            "confidence": 0.96,
        }
    )
    detector = BiasDetector(
        embedding_model=UpgradeEmbeddings(),
        classifier=LowToxicityClassifier(),
        llm_judge=judge,
    )
    result = detector.scan(
        "Women should be hired based on qualifications and experience."
    )
    assert judge.calls == 1
    assert not result.detected
    assert any(item["signal"] == "LLM_BIAS_JUDGE_SAFE" for item in result.evidence)


def test_llm_judge_unavailable_follows_explicit_failure_behavior():
    judge = MockJudge(error=RuntimeError("offline"))
    detector = BiasDetector(
        embedding_model=UpgradeEmbeddings(),
        classifier=LowToxicityClassifier(),
        llm_judge=judge,
    )
    with pytest.raises(BiasDetectorError, match="unavailable"):
        detector.scan("Female applicants should be hired based on appearance.")


def test_missing_enabled_llm_judge_fails_only_when_review_is_required():
    detector = BiasDetector(
        embedding_model=UpgradeEmbeddings(),
        classifier=LowToxicityClassifier(),
        enable_llm_judge=True,
    )
    with pytest.raises(BiasDetectorError, match="unavailable"):
        detector.scan("Female applicants should be hired based on appearance.")


def test_malformed_llm_output_is_rejected():
    judge = MockJudge({"endorses_bias": True, "confidence": "certain"})
    detector = BiasDetector(
        embedding_model=UpgradeEmbeddings(),
        classifier=LowToxicityClassifier(),
        llm_judge=judge,
    )
    with pytest.raises(BiasDetectorError, match="malformed"):
        detector.scan("Female applicants should be hired based on appearance.")


def test_ordinary_safe_response_does_not_call_llm():
    judge = MockJudge(
        {
            "endorses_bias": False,
            "protected_dimensions": [],
            "behaviors": [],
            "confidence": 0.99,
        }
    )
    detector = BiasDetector(
        embedding_model=UpgradeEmbeddings(),
        classifier=LowToxicityClassifier(),
        llm_judge=judge,
    )
    result = detector.scan("The deployment completed successfully this morning.")
    assert not result.detected
    assert judge.calls == 0
