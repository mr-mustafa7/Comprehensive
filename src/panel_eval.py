"""Evaluate the reader panel against the single reader, on all 12 labelled documents.

Both methods run fresh, on the same document bodies, with the provenance/answer-key
header stripped (see src/documents.py) — so this is a like-for-like comparison. The
locked results in outputs/results.csv and outputs/edge_case_results.csv are NOT
read or modified; this writes its own files:

    outputs/panel_results.csv   one row per document
    outputs/panel_runs.json     every teach-back and judge output, for audit
    outputs/panel_summary.csv   catch rate / false-positive rate / cost / time per method

Panel decision rule is fixed in src/panel.py (flag if any reader is flagged) and was
set before this script was first run. Run once and report what comes out — do not
tune personas or the rule against these 12 documents.

Usage:
    python -m src.panel_eval
"""

import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor

from src.baseline_readability import baseline_flag
from src.documents import read_body
from src.judge import judge_paraphrase
from src.panel import PERSONAS, panel_flagged, run_panel
from src.paraphrase import paraphrase_document
from src.pipeline import ROOT, load_documents

PANEL_RESULTS_CSV = ROOT / "outputs" / "panel_results.csv"
PANEL_RUNS_JSON = ROOT / "outputs" / "panel_runs.json"
PANEL_SUMMARY_CSV = ROOT / "outputs" / "panel_summary.csv"


def _to_bool(value) -> bool:
    return str(value).strip().upper() in ("TRUE", "1", "YES")


def run_single(document_text: str) -> dict:
    t0 = time.time()
    paraphrase_text, p_usage = paraphrase_document(document_text)
    judge = judge_paraphrase(document_text, paraphrase_text)
    j_usage = judge.pop("_usage")
    return {"paraphrase": paraphrase_text, "judge": judge, "elapsed_s": time.time() - t0,
            "cost_usd": p_usage.get("cost_usd", 0.0) + j_usage.get("cost_usd", 0.0)}


def run_panel_timed(document_text: str) -> dict:
    t0 = time.time()
    readers = run_panel(document_text)
    return {"readers": readers, "elapsed_s": time.time() - t0,
            "cost_usd": sum(r["cost_usd"] for r in readers)}


def evaluate_document(doc: dict) -> dict:
    body = read_body(ROOT / doc["source_path"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        single_future = pool.submit(run_single, body)
        panel_future = pool.submit(run_panel_timed, body)
        single, panel = single_future.result(), panel_future.result()
    return {"doc": doc, "single": single, "panel": panel,
            "baseline_flagged": bool(baseline_flag(body)["flagged"])}


def score(rows: list[dict], flag_key: str, cost_key: str | None, time_key: str | None) -> dict:
    planted = [r for r in rows if _to_bool(r["contains_planted_misunderstanding"])]
    clean = [r for r in rows if not _to_bool(r["contains_planted_misunderstanding"])]
    n_caught = sum(1 for r in planted if r[flag_key])
    n_fp = sum(1 for r in clean if r[flag_key])
    return {
        "n_caught": n_caught, "n_planted": len(planted),
        "catch_rate": round(n_caught / len(planted), 4) if planted else "",
        "n_false_positive": n_fp, "n_clean": len(clean),
        "false_positive_rate": round(n_fp / len(clean), 4) if clean else "",
        "mean_cost_usd": round(sum(r[cost_key] for r in rows) / len(rows), 4) if cost_key else 0.0,
        "mean_time_s": round(sum(r[time_key] for r in rows) / len(rows), 1) if time_key else 0.0,
    }


def main():
    documents = [d for d in load_documents() if d.get("test_set") in ("primary", "edge_case")]
    runs, rows = [], []
    for i, doc in enumerate(documents, 1):
        print(f"[{i}/{len(documents)}] {doc['doc_id']} ...", flush=True)
        run = evaluate_document(doc)
        runs.append(run)
        readers = run["panel"]["readers"]
        reader_flags = {r["persona_id"]: (None if r.get("error") else bool(r["judge"]["flagged"]))
                        for r in readers}
        row = {
            "doc_id": doc["doc_id"],
            "test_set": doc["test_set"],
            "contains_planted_misunderstanding": doc["contains_planted_misunderstanding"],
            "ground_truth_risk_type": doc["risk_type"],
            "single_flagged": bool(run["single"]["judge"]["flagged"]),
            "single_risk_type": run["single"]["judge"]["risk_type"],
            "panel_flagged": panel_flagged(readers),
            "panel_n_flagged": sum(1 for v in reader_flags.values() if v),
            "panel_n_errors": sum(1 for v in reader_flags.values() if v is None),
            **{f"reader_{pid}": flag for pid, flag in reader_flags.items()},
            "baseline_flagged": run["baseline_flagged"],
            "single_cost_usd": round(run["single"]["cost_usd"], 6),
            "panel_cost_usd": round(run["panel"]["cost_usd"], 6),
            "single_time_s": round(run["single"]["elapsed_s"], 1),
            "panel_time_s": round(run["panel"]["elapsed_s"], 1),
        }
        rows.append(row)
        print(f"    single={row['single_flagged']}  panel={row['panel_flagged']} "
              f"({row['panel_n_flagged']}/{len(PERSONAS)} readers)  "
              f"planted={doc['contains_planted_misunderstanding']}", flush=True)

        # Write as we go so a rate-limit failure part-way keeps the finished documents.
        PANEL_RESULTS_CSV.parent.mkdir(exist_ok=True)
        with open(PANEL_RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        with open(PANEL_RUNS_JSON, "w", encoding="utf-8") as f:
            json.dump(runs, f, indent=2)

    methods = [
        ("single_reader", "single_flagged", "single_cost_usd", "single_time_s"),
        ("reader_panel", "panel_flagged", "panel_cost_usd", "panel_time_s"),
        ("readability_baseline", "baseline_flagged", None, None),
    ]
    subsets = [("primary", [r for r in rows if r["test_set"] == "primary"]),
               ("edge_case", [r for r in rows if r["test_set"] == "edge_case"]),
               ("all", rows)]
    summary = []
    for subset_name, subset in subsets:
        for method, flag_key, cost_key, time_key in methods:
            summary.append({"method": method, "subset": subset_name,
                            **score(subset, flag_key, cost_key, time_key)})
    with open(PANEL_SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)

    print("\n" + "-" * 84)
    print(f"{'Method':<22}{'Subset':<11}{'Caught':<9}{'False alarms':<14}{'Mean cost':<12}{'Mean time':<10}")
    print("-" * 84)
    for s in summary:
        print(f"{s['method']:<22}{s['subset']:<11}{s['n_caught']}/{s['n_planted']:<7}"
              f"{s['n_false_positive']}/{s['n_clean']:<12}${s['mean_cost_usd']:<11}{s['mean_time_s']}s")
    print("-" * 84)
    print(f"\nn={len(rows)} documents (single run each, no retries). Header/answer key stripped "
          f"before any model call. Written to {PANEL_RESULTS_CSV.name}, {PANEL_SUMMARY_CSV.name}, "
          f"{PANEL_RUNS_JSON.name}.")


if __name__ == "__main__":
    main()
