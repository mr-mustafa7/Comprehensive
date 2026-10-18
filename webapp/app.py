"""Web UI for the comprehension-gap checker, with a human review queue.

Workflow: pick a document -> run a check (one simulated reader, or the five-reader
panel) -> every flagged run lands in the review queue as "pending" -> a named
reviewer confirms the risk, dismisses it with a reason, or edits the source and
retests it. Nothing is auto-approved or auto-rejected; every decision is logged.

Every check calls the same src/ functions as the CLI and the locked evaluation —
this UI adds the review workflow around them, it does not change the pipeline.

Run with: .venv/bin/python -m webapp.app
"""

import csv
import hashlib
import sys
import time
from datetime import date
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.documents import read_body  # noqa: E402
from src.ocr import TranscriptionError, transcribe  # noqa: E402
from src.panel import PERSONAS  # noqa: E402
from webapp import jobs, patient_view, store  # noqa: E402
from webapp.highlight import highlight  # noqa: E402

ALLOWED_IMAGE_TYPES = {
    "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
    "image/webp": "webp", "image/gif": "gif",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB

DOCUMENTS_CSV = ROOT / "data" / "documents.csv"
EVAL_SUMMARY_CSV = ROOT / "outputs" / "eval_summary.csv"
RESULTS_CSV = ROOT / "outputs" / "results.csv"
PANEL_SUMMARY_CSV = ROOT / "outputs" / "panel_summary.csv"
PANEL_RESULTS_CSV = ROOT / "outputs" / "panel_results.csv"

app = Flask(__name__)


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_documents():
    return _read_csv(DOCUMENTS_CSV)


def _find_document(doc_id: str) -> dict | None:
    return next((d for d in load_documents() if d["doc_id"] == doc_id), None)


@app.context_processor
def queue_count():
    pending = sum(1 for r in store.list_runs() if r["status"] == store.PENDING)
    return {"pending_count": pending}


@app.route("/")
def index():
    documents = load_documents()
    primary = [d for d in documents if d.get("test_set") == "primary"]
    edge = [d for d in documents if d.get("test_set") == "edge_case"]
    return render_template("index.html", primary=primary, edge=edge, personas=PERSONAS,
                           active="index")


@app.route("/start", methods=["POST"])
def start():
    doc = _find_document(request.form.get("doc_id", ""))
    if doc is None:
        return redirect(url_for("index"))
    mode = "panel" if request.form.get("mode") == "panel" else "single"
    # Only the document body is checked: the file header holds provenance and, for
    # synthetic cases, the answer key, which no model may see.
    document_text = read_body(ROOT / doc["source_path"])
    job_id = jobs.start(doc, document_text, mode)
    return redirect(url_for("job_page", job_id=job_id))


@app.route("/upload")
def upload_form():
    return render_template("upload.html", active="index", error=request.args.get("error"))


@app.route("/upload", methods=["POST"])
def upload_transcribe():
    file = request.files.get("image")
    if not file or not file.filename:
        return redirect(url_for("upload_form", error="Choose an image file first."))
    media_type = file.mimetype
    if media_type not in ALLOWED_IMAGE_TYPES:
        return redirect(url_for("upload_form", error=f"'{media_type}' isn't a supported image type — use PNG, JPEG, WebP or GIF."))
    image_bytes = file.read(MAX_UPLOAD_BYTES + 1)
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        return redirect(url_for("upload_form", error="That image is over the 10MB limit."))
    if not image_bytes:
        return redirect(url_for("upload_form", error="That file appears to be empty."))

    try:
        result = transcribe(image_bytes, media_type)
    except TranscriptionError as exc:
        return redirect(url_for("upload_form", error=f"Transcription failed: {exc}"))

    title = request.form.get("title", "").strip() or "Uploaded document"
    return render_template(
        "upload_confirm.html", active="index", title=title,
        transcribed_text=result["text"], low_confidence=result["low_confidence"],
        cost_usd=result["cost_usd"],
    )


@app.route("/upload/run", methods=["POST"])
def upload_run():
    title = request.form.get("title", "").strip() or "Uploaded document"
    text = request.form.get("text", "").replace("\r\n", "\n").strip()
    mode = "panel" if request.form.get("mode") == "panel" else "single"
    if not text:
        return redirect(url_for("upload_form", error="The transcribed text is empty — nothing to check."))

    doc = {
        "doc_id": f"uploaded_{int(time.time())}",
        "title": title,
        "is_synthetic": "FALSE",
        "source_url": "(reviewer-uploaded photo — no public source)",
        "access_date": date.today().isoformat(),
    }
    job_id = jobs.start(doc, text, mode)
    return redirect(url_for("job_page", job_id=job_id))


@app.route("/job/<job_id>")
def job_page(job_id):
    job = jobs.status(job_id)
    if job is None:
        return redirect(url_for("index"))
    return render_template("progress.html", job_id=job_id, job=job, personas=PERSONAS,
                           active="index")


@app.route("/job/<job_id>/status")
def job_status(job_id):
    job = jobs.status(job_id)
    if job is None:
        return jsonify({"state": "missing"}), 404
    if job["run_id"]:
        job["result_url"] = url_for("run_page", run_id=job["run_id"])
    return jsonify(job)


def _blamed_phrases(run: dict) -> list[tuple[str, str]]:
    return [
        (r["judge"]["source_phrase"], r["persona_name"])
        for r in run["result"]["readers"]
        if r.get("judge") and r["judge"].get("flagged") and r["judge"].get("source_phrase")
    ]


@app.route("/run/<int:run_id>")
def run_page(run_id):
    run = store.get_run(run_id)
    if run is None:
        abort(404)
    marked_text, unmatched = highlight(run["document_text"], _blamed_phrases(run))
    parent = store.get_run(run["parent_run_id"]) if run["parent_run_id"] else None
    return render_template(
        "result.html",
        run=run,
        result=run["result"],
        marked_text=marked_text,
        unmatched=unmatched,
        parent=parent,
        children=store.get_children(run_id),
        decisions=store.get_decisions(run_id),
        error=request.args.get("error"),
        active="queue",
    )


@app.route("/run/<int:run_id>/decide", methods=["POST"])
def decide(run_id):
    run = store.get_run(run_id)
    if run is None:
        abort(404)
    reviewer = request.form.get("reviewer", "").strip()
    action = request.form.get("action")
    reason = request.form.get("reason", "").strip()
    if not reviewer:
        return redirect(url_for("run_page", run_id=run_id, error="Enter your name and role before recording a decision."))
    if action not in ("confirm", "dismiss"):
        abort(400)
    if action == "dismiss" and not reason:
        return redirect(url_for("run_page", run_id=run_id, error="Dismissing a flag needs a reason, so the decision can be audited."))
    store.record_decision(run_id, reviewer, action, reason)
    return redirect(url_for("run_page", run_id=run_id))


@app.route("/run/<int:run_id>/retest", methods=["POST"])
def retest(run_id):
    """A reviewer's own edit to the source is checked again with the same mode.

    The edit is written by the human reviewer, not generated — the tool only
    re-runs its check on the new wording.
    """
    run = store.get_run(run_id)
    if run is None:
        abort(404)
    reviewer = request.form.get("reviewer", "").strip()
    edited_text = request.form.get("edited_text", "").replace("\r\n", "\n").strip()
    if not reviewer:
        return redirect(url_for("run_page", run_id=run_id, error="Enter your name and role before retesting an edit."))
    if not edited_text or edited_text == run["document_text"].strip():
        return redirect(url_for("run_page", run_id=run_id, error="The text is unchanged — edit the source before retesting."))
    doc = {
        "doc_id": run["doc_id"],
        "title": run["title"] if run["title"].startswith("Edited: ") else f"Edited: {run['title']}",
        "is_synthetic": run["is_synthetic"],
        "source_url": run["source_url"],
        "access_date": run["access_date"],
    }
    job_id = jobs.start(doc, edited_text, run["mode"], parent_run_id=run_id)
    store.record_decision(run_id, reviewer, "edit", request.form.get("reason", "").strip(),
                          child_run_id=None)
    return redirect(url_for("job_page", job_id=job_id))


@app.route("/queue")
def queue():
    runs = store.list_runs()
    pending = [r for r in runs if r["status"] == store.PENDING]
    reviewed = [r for r in runs if r["status"] in (store.CONFIRMED, store.DISMISSED, store.EDITED)]
    clear = [r for r in runs if r["status"] == store.NOT_FLAGGED]
    return render_template("queue.html", pending=pending, reviewed=reviewed, clear=clear,
                           active="queue")


@app.route("/run/<int:run_id>/patient-view")
def patient_view_page(run_id):
    run = store.get_run(run_id)
    if run is None:
        abort(404)
    view = patient_view.resolve(run)
    return render_template("patient_view.html", run=run, view=view, active="queue")


@app.route("/governance")
def governance():
    return render_template("governance.html", stats=store.governance_stats(),
                           store_runs=store.list_runs(), active="governance")


def _audit_record_text(run: dict, decisions: list[dict]) -> str:
    digest = hashlib.sha256(run["document_text"].encode("utf-8")).hexdigest()
    lines = [
        "COMPREHENSION-GAP CHECKER — AUDIT RECORD",
        "Generated from this run's stored data; not re-checked at export time.",
        "=" * 70,
        f"Run ID:            #{run['id']}",
        f"Document:          {run['title']}",
        f"Source:            {run.get('source_url') or '(not recorded)'}",
        f"Access date:       {run.get('access_date') or '(not recorded)'}",
        f"Synthetic/test case: {'yes — labelled synthetic, not a real patient document' if run.get('is_synthetic') == 'TRUE' else 'no — real, unmodified source'}",
        f"Check mode:        {'Reader panel (5 simulated readers)' if run['mode'] == 'panel' else 'Single simulated reader'}",
        f"Checked at:        {run['created_at']}",
        f"Status:            {run['status']}",
        f"Document SHA-256:  {digest}",
        "",
        "RESULT",
        "-" * 70,
        f"Flagged:  {run['result']['flagged']}  ({run['result']['n_flagged']} of {run['result']['n_readers']} readers)",
        "",
    ]
    for reader in run["result"].get("readers", []):
        judge = reader.get("judge") or {}
        lines.append(f"Reader: {reader['persona_name']}")
        if reader.get("error"):
            lines.append(f"  call failed: {reader['error']}")
        else:
            lines.append(f"  flagged:        {judge.get('flagged')}")
            lines.append(f"  risk_type:      {judge.get('risk_type')}")
            lines.append(f"  severity:       {judge.get('severity')}/5")
            lines.append(f"  confidence:     {judge.get('confidence')}")
            if judge.get("source_phrase"):
                lines.append(f"  source_phrase:  {judge['source_phrase']!r}")
            if judge.get("explanation"):
                lines.append(f"  rationale:      {judge['explanation']}")
        lines.append("")
    lines.append("HUMAN REVIEW DECISIONS")
    lines.append("-" * 70)
    if decisions:
        for d in decisions:
            lines.append(f"{d['created_at']}  {d['reviewer']}  —  {d['action']}")
            if d.get("reason"):
                lines.append(f"  reason: {d['reason']}")
    else:
        lines.append("(no decision recorded yet)")
    lines.append("")
    lines.append("This record reflects what this tool's simulated readers and judge flagged,")
    lines.append("and what a named human reviewer decided. It is not a clinical-safety")
    lines.append("certification and does not itself establish the document is safe to use.")
    return "\n".join(lines)


@app.route("/run/<int:run_id>/audit")
def audit_record(run_id):
    run = store.get_run(run_id)
    if run is None:
        abort(404)
    text = _audit_record_text(run, store.get_decisions(run_id))
    return Response(
        text,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename=audit-record-run-{run_id}.txt"},
    )


@app.route("/eval")
def eval_page():
    return render_template(
        "eval.html",
        summary=_read_csv(EVAL_SUMMARY_CSV),
        results=_read_csv(RESULTS_CSV),
        panel_summary=_read_csv(PANEL_SUMMARY_CSV),
        panel_results=_read_csv(PANEL_RESULTS_CSV),
        active="eval",
    )


if __name__ == "__main__":
    app.run(debug=False, port=5050, threaded=True)
