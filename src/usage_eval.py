"""Evaluate the new usage workflow on held-out synthetic examples only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.usage_assessment import assess_usage, rules_only_baseline

ROOT = Path(__file__).resolve().parent.parent
HELD_OUT = ROOT / "data" / "usage_assessment" / "held_out.json"
OUTPUT = ROOT / "outputs" / "usage_eval_results.json"
REGIMEN = {
    "dose_quantity": 1,
    "dose_unit": "tablet",
    "frequency_per_day": 1,
    "timing_instructions": "in the morning at the time agreed with your clinician",
    "conditions": "contact the fictional clinic if unclear",
}
INSTRUCTION = "Take one tablet once per day, in the morning at the time agreed with your clinician."


def metrics(rows: list[dict], field: str) -> dict:
    tp = sum(1 for row in rows if row["expected_discrepancy"] and row[field])
    tn = sum(1 for row in rows if not row["expected_discrepancy"] and not row[field])
    fp = sum(1 for row in rows if not row["expected_discrepancy"] and row[field])
    fn = sum(1 for row in rows if row["expected_discrepancy"] and not row[field])
    return {
        "true_positives": tp, "true_negatives": tn, "false_alarms": fp,
        "missed_discrepancies": fn,
        "sensitivity": round(tp / (tp + fn), 3) if tp + fn else None,
        "false_alarm_rate": round(fp / (fp + tn), 3) if fp + tn else None,
    }


def run() -> dict:
    examples = json.loads(HELD_OUT.read_text())
    rows = []
    for example in examples:
        baseline = rules_only_baseline(example["report"], REGIMEN)
        hybrid = assess_usage(example["report"], REGIMEN, INSTRUCTION)
        rows.append({
            "id": example["id"],
            "expected_discrepancy": example["expected_discrepancy"],
            "baseline_flagged": baseline["potential_discrepancy"],
            "hybrid_flagged": hybrid["status"] != "no_discrepancy_detected",
            "hybrid_status": hybrid["status"],
            "hybrid_types": hybrid["discrepancy_types"],
        })
    return {
        "disclosure": "Synthetic held-out medication-use examples; not clinical validation.",
        "n": len(rows),
        "baseline": metrics(rows, "baseline_flagged"),
        "hybrid_assessment": metrics(rows, "hybrid_flagged"),
        "examples": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write outputs/usage_eval_results.json")
    args = parser.parse_args()
    result = run()
    rendered = json.dumps(result, indent=2) + "\n"
    if args.write:
        OUTPUT.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
