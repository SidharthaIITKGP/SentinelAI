"""Deterministic, offline SentinelAI governance benchmark runner."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.schemas import GroundednessVerdict, RiskLevel  # noqa: E402
from core.injection_detector import _scan_regex  # noqa: E402
from engines.efficiency.model_router import route_model  # noqa: E402
from engines.responsibility.bias_check.bias_detector import (  # noqa: E402
    BiasDetector,
    CONFIG_PATH as BIAS_CONFIG_PATH,
    SENTENCE_BOUNDARY,
)
from engines.responsibility.pii_check.secret_detector import SecretDetector  # noqa: E402
from engines.responsibility.pii_detector import QUICK_PATTERNS  # noqa: E402
from engines.trust.groundedness import evaluate_claim  # noqa: E402

DEFAULT_DATASET = Path(__file__).with_name("sentinel_benchmark.json")
DEFAULT_OUTPUT = Path(__file__).with_name("results.json")


def safe_divide(numerator: float, denominator: float) -> float:
    """Divide with a deterministic zero-denominator result."""
    return numerator / denominator if denominator else 0.0


def percentile(values: Iterable[float], quantile: float) -> float:
    """Nearest-rank percentile for small, inspectable benchmark samples."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, int((len(ordered) * quantile) + 0.999999) - 1))
    return ordered[index]


def calculate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate binary detection, action, and latency metrics."""
    tp = sum(item["expected_positive"] and item["actual_positive"] for item in results)
    tn = sum(not item["expected_positive"] and not item["actual_positive"] for item in results)
    fp = sum(not item["expected_positive"] and item["actual_positive"] for item in results)
    fn = sum(item["expected_positive"] and not item["actual_positive"] for item in results)
    precision = safe_divide(tp, tp + fp)
    recall = safe_divide(tp, tp + fn)
    latencies = [float(item["latency_ms"]) for item in results]
    return {
        "cases": len(results),
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(safe_divide(2 * precision * recall, precision + recall), 6),
        "false_positive_rate": round(safe_divide(fp, fp + tn), 6),
        "false_negative_rate": round(safe_divide(fn, fn + tp), 6),
        "action_accuracy": round(
            safe_divide(sum(item["expected_action"] == item["actual_action"] for item in results), len(results)),
            6,
        ),
        "llm_calls_avoided": sum(bool(item.get("llm_call_avoided")) for item in results),
        "average_latency_ms": round(safe_divide(sum(latencies), len(latencies)), 4),
        "p95_latency_ms": round(percentile(latencies, 0.95), 4),
    }


def _explicit_bias_detected(text: str) -> bool:
    """Run the production explicit-bias layer without loading external models."""
    with BIAS_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    detector = BiasDetector.__new__(BiasDetector)
    detector.config = config
    detector.patterns = [
        (re.compile(item["pattern"], re.IGNORECASE), item)
        for item in config["patterns"]
    ]
    segments = [segment.strip() for segment in SENTENCE_BOUNDARY.split(text) if segment.strip()]
    evidence = detector._explicit(segments)  # production deterministic evidence layer
    score = max((float(item["adjusted_confidence"]) for item in evidence), default=0.0)
    return score >= float(config["final_detection_threshold"])


def evaluate_case(case: dict[str, Any]) -> tuple[bool, str, str | None]:
    """Evaluate one labeled case through the relevant production control."""
    detector = case["detector"]
    text = case.get("text", "")
    verdict: str | None = None
    if detector == "injection":
        detected, _, _ = _scan_regex(text)
        action = "BLOCK" if detected else "ALLOW"
    elif detector == "pii":
        detected = any(re.search(pattern, text) for pattern in QUICK_PATTERNS.values())
        action = "REDACT" if detected else "ALLOW"
    elif detector == "secret":
        detected = SecretDetector().scan(text).found
        action = "BLOCK" if detected else "ALLOW"
    elif detector == "bias":
        detected = _explicit_bias_detected(text)
        action = "ESCALATE" if detected else "ALLOW"
    elif detector == "groundedness":
        evaluation = evaluate_claim(
            case["claim"], case.get("evidence", []), float(case.get("threshold", 0.5))
        )
        verdict = str(evaluation.verdict)
        detected = verdict != GroundednessVerdict.SUPPORTED.value
        action = {
            GroundednessVerdict.SUPPORTED.value: "ALLOW",
            GroundednessVerdict.CONTRADICTED.value: "REPAIR",
            GroundednessVerdict.INSUFFICIENT_EVIDENCE.value: "ESCALATE",
        }.get(verdict, "ESCALATE")
    else:
        raise ValueError(f"Unknown benchmark detector: {detector}")
    return bool(detected), action, verdict


def run_benchmark(dataset_path: Path = DEFAULT_DATASET, output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    """Run all cases offline and persist aggregate, category, and safe case results."""
    with dataset_path.open("r", encoding="utf-8") as handle:
        cases = json.load(handle)["cases"]
    results: list[dict[str, Any]] = []
    selected_cost = baseline_cost = savings = 0.0
    tiers: dict[str, int] = {}
    for case in cases:
        started = perf_counter()
        actual_positive, actual_action, verdict = evaluate_case(case)
        route = route_model(case["risk_level"], case["use_case"], case.get("text") or case.get("claim", ""))
        latency_ms = (perf_counter() - started) * 1000
        selected_cost += float(route.estimated_cost_usd or 0.0)
        baseline_cost += route.baseline_estimated_cost_usd
        savings += route.estimated_savings_usd
        tier = str(route.selected_tier)
        tiers[tier] = tiers.get(tier, 0) + 1
        results.append({
            "id": case["id"], "category": case["category"],
            "expected_positive": bool(case["expected_positive"]),
            "actual_positive": actual_positive,
            "expected_action": case["expected_action"], "actual_action": actual_action,
            "actual_verdict": verdict, "latency_ms": round(latency_ms, 4),
            "selected_tier": tier,
            "llm_call_avoided": actual_action == "BLOCK",
        })

    categories = sorted({item["category"] for item in results})
    report = {
        "benchmark": "SentinelAI Phase 6 offline governance benchmark",
        "dataset_version": 1,
        "metrics": calculate_metrics(results),
        "per_category": {
            category: calculate_metrics([item for item in results if item["category"] == category])
            for category in categories
        },
        "routing_costs": {
            "label": "ESTIMATED — deterministic registry profiles, not provider billing",
            "selected_cost_usd": round(selected_cost, 8),
            "baseline_cost_usd": round(baseline_cost, 8),
            "estimated_savings_usd": round(savings, 8),
            "selected_tier_counts": tiers,
        },
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_benchmark(args.dataset, args.output)
    metrics = report["metrics"]
    print(
        "SentinelAI benchmark: "
        f"cases={metrics['cases']} precision={metrics['precision']:.3f} "
        f"recall={metrics['recall']:.3f} f1={metrics['f1']:.3f} "
        f"action_accuracy={metrics['action_accuracy']:.3f} "
        f"avg_ms={metrics['average_latency_ms']:.3f} p95_ms={metrics['p95_latency_ms']:.3f}"
    )
    print(report["routing_costs"]["label"])
    print(f"Results written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
