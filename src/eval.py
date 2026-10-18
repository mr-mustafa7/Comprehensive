"""Compute catch-rate and false-positive-rate for our method vs. the readability
baseline, against the labelled test set in data/documents.csv.

Usage:
    python -m src.eval
Requires outputs/results.csv to exist (run `python -m src.pipeline --all` first).
"""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_CSV = ROOT / "outputs" / "results.csv"
SUMMARY_CSV = ROOT / "outputs" / "eval_summary.csv"


def _to_bool(value: str) -> bool:
    return str(value).strip().upper() in ("TRUE", "1", "YES")


def load_results():
    with open(RESULTS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def score(results, flag_field: str):
    """Return (catch_rate, n_planted, false_positive_rate, n_clean) for one method."""
    planted = [r for r in results if _to_bool(r["contains_planted_misunderstanding"])]
    clean = [r for r in results if not _to_bool(r["contains_planted_misunderstanding"])]

    n_caught = sum(1 for r in planted if _to_bool(r[flag_field]))
    n_false_positive = sum(1 for r in clean if _to_bool(r[flag_field]))

    catch_rate = n_caught / len(planted) if planted else float("nan")
    fpr = n_false_positive / len(clean) if clean else float("nan")

    return {
        "catch_rate": catch_rate,
        "n_caught": n_caught,
        "n_planted": len(planted),
        "false_positive_rate": fpr,
        "n_false_positive": n_false_positive,
        "n_clean": len(clean),
    }


def main():
    if not RESULTS_CSV.exists():
        raise SystemExit(
            f"{RESULTS_CSV} not found — run `python -m src.pipeline --all` first."
        )
    results = load_results()

    our_method = score(results, "method_flagged")
    baseline = score(results, "baseline_flagged")

    print(f"\nLabelled test set: {len(results)} documents "
          f"({our_method['n_planted']} with a planted misunderstanding, "
          f"{our_method['n_clean']} clean/control)")
    print("\n" + "-" * 72)
    print(f"{'Method':<32}{'Catch rate':<18}{'False-positive rate':<22}")
    print("-" * 72)
    for name, s in [("Comprehension-gap checker", our_method), ("Readability-score baseline", baseline)]:
        catch_str = f"{s['n_caught']}/{s['n_planted']} ({s['catch_rate']:.0%})"
        fpr_str = f"{s['n_false_positive']}/{s['n_clean']} ({s['false_positive_rate']:.0%})"
        print(f"{name:<32}{catch_str:<18}{fpr_str:<22}")
    print("-" * 72)
    print(
        "\nSample size is small (n={}) — a hackathon-weekend test set, not a "
        "population-level validation. See README 'Honest limits'.".format(len(results))
    )

    SUMMARY_CSV.parent.mkdir(exist_ok=True)
    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["method", "n_caught", "n_planted", "catch_rate",
                          "n_false_positive", "n_clean", "false_positive_rate"])
        for name, s in [("comprehension_gap_checker", our_method), ("readability_baseline", baseline)]:
            writer.writerow([name, s["n_caught"], s["n_planted"], round(s["catch_rate"], 4),
                              s["n_false_positive"], s["n_clean"], round(s["false_positive_rate"], 4)])
    print(f"\nSummary written to {SUMMARY_CSV}")


if __name__ == "__main__":
    main()
