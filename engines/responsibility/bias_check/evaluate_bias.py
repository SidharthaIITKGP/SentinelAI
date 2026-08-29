"""Run deterministic bias validation cases without downloading models."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from engines.responsibility.bias_check.bias_detector import BiasDetector


class LexicalEmbeddings:
    """Stable evaluation surrogate; production uses sentence embeddings."""

    def encode(self, texts, *, normalize_embeddings=True):
        assert normalize_embeddings is True

        def vector(text):
            lowered = text.casefold()
            groups = (
                ("men", "male", "women", "female"),
                ("older", "younger", "age"),
                ("wealthy", "poor"),
                ("religion", "muslim"),
                ("ethnic", "race"),
                ("disability", "disabled"),
                ("nationality",),
                ("gay", "lesbian", "sexual orientation"),
                ("married", "parents", "mothers"),
            )
            return [float(any(word in lowered for word in words)) for words in groups]

        return [vector(text) for text in texts]


class Classifier:
    def __call__(self, text):
        return [{"label": "non-toxic", "score": 0.0}]


def metrics(rows, predictions):
    tp = fp = tn = fn = 0
    for row, predicted in zip(rows, predictions):
        actual = row["biased"]
        tp += bool(predicted and actual)
        fp += bool(predicted and not actual)
        tn += bool(not predicted and not actual)
        fn += bool(not predicted and actual)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fpr": fp / (fp + tn) if fp + tn else 0.0,
        "fnr": fn / (fn + tp) if fn + tp else 0.0,
    }


def print_metrics(label, values):
    print(
        f"{label} precision={values['precision']:.3f} "
        f"recall={values['recall']:.3f} F1={values['f1']:.3f} "
        f"FPR={values['fpr']:.3f} FNR={values['fnr']:.3f}"
    )


def main():
    data_path = Path(__file__).with_name("bias_validation.json")
    data = json.loads(data_path.read_text(encoding="utf-8"))
    detector = BiasDetector(
        embedding_model=LexicalEmbeddings(), classifier=Classifier()
    )
    scores = [detector.scan(row["text"]).risk_score for row in data]

    for threshold in (0.50, 0.62, 0.75):
        predictions = [score >= threshold for score in scores]
        print_metrics(f"threshold={threshold:.2f}", metrics(data, predictions))

    selected = 0.62
    groups = sorted({row["group"] for row in data})
    print(f"selected_threshold={selected:.2f} group_breakdown")
    for group in groups:
        indexes = [index for index, row in enumerate(data) if row["group"] == group]
        rows = [data[index] for index in indexes]
        predictions = [scores[index] >= selected for index in indexes]
        print_metrics(f"group={group}", metrics(rows, predictions))


if __name__ == "__main__":
    main()
