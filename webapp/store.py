"""Review-queue storage: every check the web UI runs, and every reviewer decision on it.

SQLite file at outputs/review.db (created on first use). Nothing in here changes a
check's result — a flag can only be confirmed, dismissed (with a reason) or answered
by a human edit that is then retested. Every decision is kept, with who made it and
when, so the history of a document can be audited after the fact.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "outputs" / "review.db"

# Statuses a run can be in. Only flagged runs ever enter the queue as "pending".
PENDING = "pending"
CONFIRMED = "confirmed"          # reviewer agrees the risk is real; source must not go out as-is
DISMISSED = "dismissed"          # reviewer judged it a false alarm, with a stated reason
EDITED = "edited"                # reviewer rewrote the source; see the linked retest run
NOT_FLAGGED = "not_flagged"      # the check raised nothing; no review needed

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    doc_id TEXT,
    title TEXT NOT NULL,
    is_synthetic TEXT,
    source_url TEXT,
    access_date TEXT,
    mode TEXT NOT NULL,
    parent_run_id INTEGER REFERENCES runs(id),
    document_text TEXT NOT NULL,
    result_json TEXT NOT NULL,
    flagged INTEGER NOT NULL,
    status TEXT NOT NULL,
    elapsed_s REAL,
    cost_usd REAL
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    created_at TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT,
    child_run_id INTEGER REFERENCES runs(id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _row_to_run(row: sqlite3.Row) -> dict:
    run = dict(row)
    run["result"] = json.loads(run.pop("result_json"))
    return run


def save_run(doc: dict, document_text: str, mode: str, result: dict,
             elapsed_s: float, cost_usd: float, parent_run_id: int | None = None) -> int:
    flagged = bool(result["flagged"])
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO runs (created_at, doc_id, title, is_synthetic, source_url, access_date, "
            "mode, parent_run_id, document_text, result_json, flagged, status, elapsed_s, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), doc.get("doc_id"), doc["title"], doc.get("is_synthetic"),
             doc.get("source_url"), doc.get("access_date"), mode, parent_run_id,
             document_text, json.dumps(result), int(flagged),
             PENDING if flagged else NOT_FLAGGED, elapsed_s, cost_usd),
        )
        return cur.lastrowid


def get_run(run_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return _row_to_run(row) if row else None


def get_children(run_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE parent_run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    return [_row_to_run(r) for r in rows]


def list_runs() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    return [_row_to_run(r) for r in rows]


def get_decisions(run_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def governance_stats() -> dict:
    """Aggregate every run for the governance view: counts, risk-type and severity
    breakdowns, and a per-day trend. Pure read over what's already stored — this
    does not re-run or re-score anything.
    """
    runs = list_runs()

    status_counts = {PENDING: 0, CONFIRMED: 0, DISMISSED: 0, EDITED: 0, NOT_FLAGGED: 0}
    risk_type_counts: dict[str, int] = {}
    severity_buckets = {"low (1-2)": 0, "medium (3)": 0, "high (4-5)": 0}
    by_day: dict[str, int] = {}

    for run in runs:
        status_counts[run["status"]] = status_counts.get(run["status"], 0) + 1
        by_day[run["created_at"][:10]] = by_day.get(run["created_at"][:10], 0) + 1
        for reader in run["result"].get("readers", []):
            judge = reader.get("judge")
            if not judge or not judge.get("flagged"):
                continue
            risk_type = judge.get("risk_type") or "unspecified"
            risk_type_counts[risk_type] = risk_type_counts.get(risk_type, 0) + 1
            severity = judge.get("severity") or 0
            bucket = "high (4-5)" if severity >= 4 else "medium (3)" if severity == 3 else "low (1-2)"
            severity_buckets[bucket] += 1

    return {
        "total_runs": len(runs),
        "flagged_runs": sum(1 for r in runs if r["flagged"]),
        "status_counts": status_counts,
        "risk_type_counts": dict(sorted(risk_type_counts.items(), key=lambda kv: -kv[1])),
        "severity_buckets": severity_buckets,
        "by_day": dict(sorted(by_day.items())),
        "total_cost_usd": round(sum(r["cost_usd"] or 0.0 for r in runs), 4),
    }


def record_decision(run_id: int, reviewer: str, action: str, reason: str = "",
                    child_run_id: int | None = None) -> None:
    new_status = {"confirm": CONFIRMED, "dismiss": DISMISSED, "edit": EDITED}[action]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO decisions (run_id, created_at, reviewer, action, reason, child_run_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, _now(), reviewer, action, reason, child_run_id),
        )
        conn.execute("UPDATE runs SET status = ? WHERE id = ?", (new_status, run_id))
