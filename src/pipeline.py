"""CLI entry point: run the comprehension-gap checker over one or all documents.

Usage:
    python -m src.pipeline --doc data/sources/pil_amoxicillin_250mg_capsules.txt
    python -m src.pipeline --all
"""

import argparse
import csv
import sys
from pathlib import Path

from src.baseline_readability import baseline_flag
from src.documents import read_body
from src.judge import judge_paraphrase
from src.paraphrase import paraphrase_document

ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS_CSV = ROOT / "data" / "documents.csv"
RESULTS_CSV = ROOT / "outputs" / "results.csv"
EDGE_CASE_RESULTS_CSV = ROOT / "outputs" / "edge_case_results.csv"

# Plain ANSI codes, no extra dependency — purely to make a live terminal recording
# easier to follow (separating "simulated reader" / "judge verdict" / "baseline" at
# a glance). Degrades harmlessly to visible escape codes if piped somewhere that
# doesn't render them; doesn't affect outputs/*.csv, which store plain text only.
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"


def _flag_banner(flagged: bool, flagged_label: str = "FLAGGED") -> str:
    if flagged:
        return f"{BOLD}{RED}⚠ {flagged_label}{RESET}"
    return f"{BOLD}{GREEN}✓ not flagged{RESET}"


def load_documents():
    with open(DOCUMENTS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_one(doc_row: dict, verbose: bool = True) -> dict:
    doc_path = ROOT / doc_row["source_path"]
    # read_body() strips the file's provenance header (which, on synthetic files,
    # states the answer key) before any model sees the text — see src/documents.py.
    document_text = read_body(doc_path)

    if verbose:
        print(f"\n{CYAN}{'=' * 70}{RESET}")
        print(f"{BOLD}{CYAN}DOCUMENT: {doc_row['title']}{RESET}  {DIM}(doc_id={doc_row['doc_id']}){RESET}")
        if doc_row["is_synthetic"] == "TRUE":
            print(f"  {BOLD}{YELLOW}*** SYNTHETIC / MODIFIED TEST CASE — not a real patient document ***{RESET}")
        print(f"  {DIM}source: {doc_row['source_url']}  (accessed {doc_row['access_date']}){RESET}")
        print(f"{CYAN}{'=' * 70}{RESET}")

    paraphrase_text, paraphrase_usage = paraphrase_document(document_text)
    if verbose:
        print(f"\n{BOLD}[1/3] Layperson teach-back (simulated reader — not a real patient):{RESET}")
        print(f"  {paraphrase_text}")

    judge_result = judge_paraphrase(document_text, paraphrase_text)
    judge_usage = judge_result.pop("_usage")
    if verbose:
        print(f"\n{BOLD}[2/3] Judge — misunderstanding-risk check (not groundedness):{RESET}")
        print(f"  {_flag_banner(judge_result['flagged'], 'FLAGGED — sent to human review queue')}")
        print(f"  risk_type:     {judge_result['risk_type']}")
        print(f"  severity:      {judge_result['severity']}/5")
        print(f"  confidence:    {judge_result['confidence']}")
        if judge_result["source_phrase"]:
            print(f"  source_phrase: {MAGENTA}{judge_result['source_phrase']!r}{RESET}")
        if judge_result["explanation"]:
            print(f"  explanation:   {judge_result['explanation']}")

    baseline_result = baseline_flag(document_text)
    if verbose:
        print(f"\n{BOLD}[3/3] Baseline — plain readability-score flag:{RESET}")
        print(f"  flesch_kincaid_grade: {baseline_result['flesch_kincaid_grade']:.1f}")
        print(f"  smog_index:           {baseline_result['smog_index']:.1f}")
        print(f"  {_flag_banner(baseline_result['flagged'], 'FLAGGED (readability over threshold)')}")

    run_cost = paraphrase_usage.get("cost_usd", 0.0) + judge_usage.get("cost_usd", 0.0)

    return {
        "doc_id": doc_row["doc_id"],
        "title": doc_row["title"],
        "is_synthetic": doc_row["is_synthetic"],
        "contains_planted_misunderstanding": doc_row["contains_planted_misunderstanding"],
        "ground_truth_risk_type": doc_row["risk_type"],
        "paraphrase_text": paraphrase_text,
        "method_flagged": judge_result["flagged"],
        "method_risk_type": judge_result["risk_type"],
        "method_severity": judge_result["severity"],
        "method_confidence": judge_result["confidence"],
        "method_source_phrase": judge_result["source_phrase"],
        "method_explanation": judge_result["explanation"],
        "baseline_flesch_kincaid_grade": round(baseline_result["flesch_kincaid_grade"], 2),
        "baseline_smog_index": round(baseline_result["smog_index"], 2),
        "baseline_flagged": baseline_result["flagged"],
        "paraphrase_cost_usd": paraphrase_usage.get("cost_usd", 0.0),
        "judge_cost_usd": judge_usage.get("cost_usd", 0.0),
        "run_cost_usd": round(run_cost, 6),
    }


def run_set(documents: list[dict], out_csv: Path, label: str):
    results = []
    total_cost = 0.0
    for doc_row in documents:
        result = run_one(doc_row)
        results.append(result)
        total_cost += result["run_cost_usd"]

    out_csv.parent.mkdir(exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print(f"\n{'=' * 70}")
    print(f"Ran {len(results)} {label} documents. Total CLI-reported cost: ${total_cost:.4f}")
    print(f"Results written to {out_csv}")
    print(f"{'=' * 70}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", help="Path to a single document to run")
    parser.add_argument("--all", action="store_true",
                         help="Run the primary labelled test set (test_set=primary) -> outputs/results.csv")
    parser.add_argument("--edge-cases", action="store_true",
                         help="Run the extended edge-case set (test_set=edge_case) -> outputs/edge_case_results.csv. "
                              "Kept separate from --all so it can never silently change the headline eval numbers.")
    args = parser.parse_args()

    documents = load_documents()

    if args.doc:
        matches = [d for d in documents if d["source_path"] == args.doc or str(ROOT / d["source_path"]) == args.doc]
        if not matches:
            print(f"ERROR: {args.doc} not found in {DOCUMENTS_CSV}", file=sys.stderr)
            sys.exit(1)
        run_one(matches[0])
        return

    if args.edge_cases:
        edge_docs = [d for d in documents if d.get("test_set") == "edge_case"]
        run_set(edge_docs, EDGE_CASE_RESULTS_CSV, "edge-case")
        return

    if not args.all:
        parser.print_help()
        sys.exit(1)

    primary_docs = [d for d in documents if d.get("test_set") == "primary"]
    run_set(primary_docs, RESULTS_CSV, "primary")


if __name__ == "__main__":
    main()
