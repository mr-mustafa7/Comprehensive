"""Run checks in a background thread so the browser can show each reader as it finishes.

A check takes 20-60s (two model calls per simulated reader). Rather than holding the
page load open, /start returns straight away with a job id; the progress page polls
/job/<id>/status and moves to the saved result once the run is stored.

Jobs live in memory only — a server restart drops in-flight jobs, never saved runs.
"""

import threading
import time
import uuid

from src.baseline_readability import baseline_flag
from src.judge import judge_paraphrase
from src.panel import PERSONAS, panel_flagged, run_panel
from src.paraphrase import paraphrase_document
from webapp import store

SINGLE_READER = {
    "id": "default",
    "name": "Single simulated reader",
    "description": "The original one-reader teach-back used in the locked evaluation.",
}

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _run_single(document_text: str, on_reader_done) -> list[dict]:
    paraphrase_text, paraphrase_usage = paraphrase_document(document_text)
    judge_result = judge_paraphrase(document_text, paraphrase_text)
    judge_usage = judge_result.pop("_usage")
    reader = {
        "persona_id": SINGLE_READER["id"],
        "persona_name": SINGLE_READER["name"],
        "persona_description": SINGLE_READER["description"],
        "paraphrase": paraphrase_text,
        "judge": judge_result,
        "cost_usd": paraphrase_usage.get("cost_usd", 0.0) + judge_usage.get("cost_usd", 0.0),
    }
    on_reader_done(reader)
    return [reader]


def run_check(doc: dict, document_text: str, mode: str, on_reader_done=lambda r: None,
              parent_run_id: int | None = None) -> int:
    """Run the full check (single reader or panel) plus the baseline, save it, return run id."""
    t0 = time.time()
    if mode == "panel":
        readers = run_panel(document_text, on_reader_done)
    else:
        readers = _run_single(document_text, on_reader_done)
    baseline = baseline_flag(document_text)
    elapsed = time.time() - t0

    judged = [r for r in readers if r.get("judge")]
    result = {
        "readers": readers,
        "flagged": panel_flagged(readers),
        "n_flagged": sum(1 for r in judged if r["judge"].get("flagged")),
        "n_readers": len(readers),
        "n_errors": len(readers) - len(judged),
        "baseline": {
            "flesch_kincaid_grade": baseline["flesch_kincaid_grade"],
            "smog_index": baseline["smog_index"],
            "flagged": bool(baseline["flagged"]),
        },
    }
    cost = sum(r.get("cost_usd", 0.0) for r in readers)
    return store.save_run(doc, document_text, mode, result, round(elapsed, 1), round(cost, 4),
                          parent_run_id=parent_run_id)


def start(doc: dict, document_text: str, mode: str, parent_run_id: int | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    total = len(PERSONAS) if mode == "panel" else 1
    with _LOCK:
        _JOBS[job_id] = {"state": "running", "title": doc["title"], "mode": mode,
                         "total": total, "done": [], "run_id": None, "error": None,
                         "started": time.time()}

    def on_reader_done(reader):
        flagged = bool(reader.get("judge") and reader["judge"].get("flagged"))
        with _LOCK:
            _JOBS[job_id]["done"].append({"name": reader["persona_name"], "flagged": flagged,
                                          "error": bool(reader.get("error"))})

    def work():
        try:
            run_id = run_check(doc, document_text, mode, on_reader_done, parent_run_id)
            with _LOCK:
                _JOBS[job_id].update(state="done", run_id=run_id)
        except Exception as exc:  # surface model/CLI failures on the progress page
            with _LOCK:
                _JOBS[job_id].update(state="error", error=str(exc))

    threading.Thread(target=work, daemon=True).start()
    return job_id


def status(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        return {**job, "done": list(job["done"]), "elapsed": round(time.time() - job["started"])}
