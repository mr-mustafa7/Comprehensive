"""Authenticated clinician and patient routes for Comprehensive 2.0."""

from __future__ import annotations

import json
from io import BytesIO
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from src.document_feedback import suggest_improvement
from src.document_summary import summarize_assignment
from src.usage_assessment import ClaudeUsageAdapter, assess_usage, validate_assessment
from webapp import clinical_store
from webapp.security import csrf_token, login_required, role_required, valid_password

bp = Blueprint("clinical", __name__)
ROOT = Path(__file__).resolve().parent.parent


def _safe_next(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    return value if not parsed.scheme and not parsed.netloc and value.startswith("/") else None


def _optional_float(value: str) -> float | None:
    if not value.strip():
        return None
    return float(value)


def _optional_int(value: str) -> int | None:
    if not value.strip():
        return None
    number = int(value)
    return number


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("home"))
    if request.method == "POST":
        user = clinical_store.get_user_by_email(request.form.get("email", ""))
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            csrf_token()  # rotate the token at the authentication boundary
            clinical_store.audit(user["id"], "auth.login", "user", user["id"])
            destination = url_for("clinical.clinician_dashboard" if user["role"] == "clinician" else "clinical.patient_dashboard")
            return redirect(_safe_next(request.form.get("next")) or destination)
        flash("Email or password was not recognised.", "error")
    return render_template("signin.html", next=_safe_next(request.args.get("next")), active="login")


@bp.post("/logout")
@login_required
def logout():
    user_id = g.user["id"]
    clinical_store.audit(user_id, "auth.logout", "user", user_id)
    session.clear()
    return redirect(url_for("clinical.login"))


@bp.route("/activate/<token>", methods=["GET", "POST"])
def activate(token: str):
    invitation = clinical_store.get_invitation_by_token(token)
    if request.method == "POST":
        password = request.form.get("password", "")
        name = request.form.get("display_name", "").strip()
        if not name:
            flash("Enter your name.", "error")
        elif not valid_password(password):
            flash("Use at least 12 characters with upper-case, lower-case, and a number.", "error")
        elif password != request.form.get("password_confirm", ""):
            flash("The passwords do not match.", "error")
        else:
            try:
                patient_id = clinical_store.accept_invitation(token, password, name)
            except (ValueError, TypeError) as exc:
                flash(str(exc), "error")
            else:
                session.clear()
                session["user_id"] = patient_id
                csrf_token()
                flash("Your account is active.", "success")
                return redirect(url_for("clinical.patient_dashboard"))
    return render_template("activate.html", invitation=invitation, token=token, active="login")


@bp.get("/clinician")
@role_required("clinician")
def clinician_dashboard():
    patients = clinical_store.list_patients(g.user["id"])
    reports = clinical_store.list_reports_for_clinician(g.user["id"], 12)
    pending = [r for r in reports if r.get("assessment_status") in {"review_required", "analysis_incomplete"} and not r.get("review_decision")]
    suggestions = clinical_store.list_suggestions(g.user["id"], "pending")
    return render_template(
        "clinician_dashboard.html", patients=patients, reports=reports, pending=pending,
        suggestions=suggestions, documents=clinical_store.list_documents(g.user["id"]),
        activity=clinical_store.recent_audit(g.user["id"]),
        clarifications=clinical_store.count_open_clarifications(g.user["id"]), active="clinician",
    )


@bp.get("/clinician/usage-evaluation")
@role_required("clinician")
def usage_evaluation():
    path = ROOT / "outputs" / "usage_eval_results.json"
    results = json.loads(path.read_text()) if path.exists() else None
    return render_template("usage_evaluation.html", results=results, active="evaluation")


@bp.post("/clinician/invitations")
@role_required("clinician")
def invite_patient():
    email = request.form.get("email", "").strip().lower()
    if "@" not in email or len(email) > 254:
        flash("Enter a valid patient email address.", "error")
        return redirect(url_for("clinical.clinician_dashboard"))
    try:
        invitation_id, token = clinical_store.create_invitation(g.user["id"], email)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        # The raw single-use token is shown once; only its SHA-256 hash is stored.
        flash(f"Invitation created. Activation link: {url_for('clinical.activate', token=token, _external=True)}", "success")
    return redirect(url_for("clinical.clinician_dashboard"))


@bp.get("/clinician/patients/<int:patient_id>")
@role_required("clinician")
def clinician_patient(patient_id: int):
    if not clinical_store.clinician_can_access(g.user["id"], patient_id):
        abort(404)
    patient = clinical_store.get_user(patient_id)
    return render_template(
        "clinician_patient.html", patient=patient,
        assignments=clinical_store.list_assignments(patient_id),
        reports=clinical_store.list_reports_for_patient(patient_id),
        documents=clinical_store.list_documents(g.user["id"]),
        approved_versions=clinical_store.list_approved_versions(g.user["id"]), active="clinician",
    )


@bp.post("/clinician/patients/<int:patient_id>/assign")
@role_required("clinician")
def assign_patient(patient_id: int):
    if not clinical_store.clinician_can_access(g.user["id"], patient_id):
        abort(404)
    try:
        quantity = float(request.form.get("dose_quantity", ""))
        frequency = int(request.form.get("frequency_per_day", ""))
        version_id = int(request.form.get("document_version_id", ""))
        if quantity <= 0 or frequency <= 0 or frequency > 24:
            raise ValueError
        clinical_store.assign_regimen(
            g.user["id"], patient_id, version_id, request.form.get("medication_name", "").strip(),
            quantity, request.form.get("dose_unit", "").strip(), frequency,
            request.form.get("timing_instructions", "").strip(), request.form.get("conditions", "").strip(),
            request.form.get("effective_from", "") or date.today().isoformat(),
        )
    except (ValueError, TypeError, PermissionError):
        flash("Check the approved version, quantity, unit, frequency, and medication name.", "error")
    else:
        flash("Approved regimen assigned. The version is now fixed for future report history.", "success")
    return redirect(url_for("clinical.clinician_patient", patient_id=patient_id))


@bp.route("/clinician/documents", methods=["GET", "POST"])
@role_required("clinician")
def documents():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        text = request.form.get("text", "").strip()
        uploaded = request.files.get("document_file")
        if uploaded and uploaded.filename:
            if not uploaded.filename.lower().endswith((".txt", ".md")):
                flash("Upload a UTF-8 .txt or .md documentation file.", "error")
                return render_template("documents.html", documents=clinical_store.list_documents(g.user["id"]), active="documents")
            raw = uploaded.read(128 * 1024 + 1)
            if len(raw) > 128 * 1024:
                flash("Documentation text files must be 128 KB or smaller.", "error")
                return render_template("documents.html", documents=clinical_store.list_documents(g.user["id"]), active="documents")
            try:
                text = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                flash("The documentation file must use UTF-8 text encoding.", "error")
                return render_template("documents.html", documents=clinical_store.list_documents(g.user["id"]), active="documents")
        source = request.form.get("source", "").strip()
        provenance = request.form.get("provenance", "").strip()
        if not title or not text or not source or not provenance:
            flash("Title, source, provenance, and approved documentation text are required.", "error")
        else:
            document_id, _ = clinical_store.create_document(g.user["id"], title, source, provenance, text)
            flash("Document and approved version 1 created.", "success")
            return redirect(url_for("clinical.document_detail", document_id=document_id))
    return render_template("documents.html", documents=clinical_store.list_documents(g.user["id"]), active="documents")


@bp.get("/clinician/documents/<int:document_id>")
@role_required("clinician")
def document_detail(document_id: int):
    document = clinical_store.get_document(document_id, g.user["id"])
    if not document:
        abort(404)
    suggestions = [s for s in clinical_store.list_suggestions(g.user["id"]) if s["document_version_id"] in {v["id"] for v in document["versions"]}]
    return render_template("document_detail.html", document=document, suggestions=suggestions, active="documents")


@bp.get("/clinician/reports/<int:report_id>")
@role_required("clinician")
def clinician_report(report_id: int):
    report = clinical_store.get_report(report_id)
    if not report or not clinical_store.clinician_can_access(g.user["id"], report["patient_id"]):
        abort(404)
    patient = clinical_store.get_user(report["patient_id"])
    suggestions = [s for s in clinical_store.list_suggestions(g.user["id"]) if s["document_version_id"] == report["document_version_id"]]
    return render_template("clinician_report.html", report=report, patient=patient, suggestions=suggestions, active="clinician")


@bp.post("/clinician/assessments/<int:assessment_id>/review")
@role_required("clinician")
def review_assessment(assessment_id: int):
    decision = request.form.get("decision", "")
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Record a reason for the review decision.", "error")
        return redirect(request.referrer or url_for("clinical.clinician_dashboard"))
    try:
        amendment = reason if decision == "amended" else ""
        clinical_store.review_assessment(assessment_id, g.user["id"], decision, reason, amendment)
    except (ValueError, PermissionError):
        abort(404)
    flash("Clinician review decision recorded for later evaluation.", "success")
    return redirect(request.referrer or url_for("clinical.clinician_dashboard"))


@bp.get("/clinician/suggestions/<int:suggestion_id>")
@role_required("clinician")
def suggestion_detail(suggestion_id: int):
    suggestion = clinical_store.get_suggestion(suggestion_id, g.user["id"])
    if not suggestion:
        abort(404)
    return render_template("suggestion_detail.html", suggestion=suggestion, active="documents")


@bp.post("/clinician/suggestions/<int:suggestion_id>/review")
@role_required("clinician")
def review_suggestion(suggestion_id: int):
    action = request.form.get("action", "")
    reason = request.form.get("reason", "").strip()
    wording = request.form.get("wording", "").strip()
    if not reason:
        flash("Record a reason for approving or rejecting the suggestion.", "error")
        return redirect(url_for("clinical.suggestion_detail", suggestion_id=suggestion_id))
    try:
        version_id = clinical_store.review_suggestion(suggestion_id, g.user["id"], action, wording, reason)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("clinical.suggestion_detail", suggestion_id=suggestion_id))
    flash("Suggestion approved and a new immutable version was assigned." if version_id else "Suggestion rejected; the original remains unchanged.", "success")
    return redirect(url_for("clinical.suggestion_detail", suggestion_id=suggestion_id))


@bp.get("/patient")
@role_required("patient")
def patient_dashboard():
    return render_template(
        "patient_dashboard.html", assignments=clinical_store.list_assignments(g.user["id"], True),
        reports=clinical_store.list_reports_for_patient(g.user["id"]), active="patient",
    )


@bp.get("/patient/assignments/<int:assignment_id>")
@role_required("patient")
def patient_assignment(assignment_id: int):
    assignment = clinical_store.get_assignment(assignment_id)
    if not assignment or assignment["patient_id"] != g.user["id"]:
        abort(404)
    summary = summarize_assignment(
        assignment,
        use_ai=current_app.config.get("DOCUMENT_SUMMARY_PROVIDER") == "claude",
    )
    return render_template("patient_assignment.html", assignment=assignment, summary=summary, active="patient")


@bp.get("/patient/assignments/<int:assignment_id>/download")
@role_required("patient")
def patient_assignment_download(assignment_id: int):
    assignment = clinical_store.get_assignment(assignment_id)
    if not assignment or assignment["patient_id"] != g.user["id"]:
        abort(404)
    filename = secure_filename(
        f"{assignment['medication_name']}-approved-v{assignment['version_number']}.txt"
    ) or f"approved-document-v{assignment['version_number']}.txt"
    return send_file(
        BytesIO(assignment["instruction_text"].encode("utf-8")),
        mimetype="text/plain; charset=utf-8",
        as_attachment=True,
        download_name=filename,
    )


@bp.route("/patient/report", methods=["GET", "POST"])
@role_required("patient")
def patient_report():
    assignments = clinical_store.list_assignments(g.user["id"], True)
    selected = request.values.get("assignment_id", "")
    if request.method == "POST":
        try:
            assignment_id = int(selected)
            assignment = clinical_store.get_assignment(assignment_id)
            if not assignment or assignment["patient_id"] != g.user["id"] or assignment["status"] != "active":
                raise PermissionError
            uncertain = bool(request.form.get("uncertain"))
            doses = _optional_int(request.form.get("number_of_doses", ""))
            quantity = _optional_float(request.form.get("quantity_per_dose", ""))
            if not uncertain and (doses is None or quantity is None):
                raise ValueError("Provide dose details or select the uncertainty option.")
            if doses is not None and (doses < 0 or doses > 48):
                raise ValueError("Number of doses is outside the supported range.")
            if quantity is not None and (quantity <= 0 or quantity > 100):
                raise ValueError("Quantity is outside the supported range.")
            usage_date = request.form.get("reported_usage_date", "")
            if not usage_date or usage_date > date.today().isoformat():
                raise ValueError("Choose today or an earlier date.")
            report_id = clinical_store.create_report(
                g.user["id"], assignment_id, usage_date, doses, quantity,
                request.form.get("timing_information", ""), request.form.get("explanation", ""), uncertain,
            )
            report_data = {
                "number_of_doses": doses, "quantity_per_dose": quantity,
                "timing_information": request.form.get("timing_information", ""),
                "explanation": request.form.get("explanation", ""), "uncertain": uncertain,
            }
            regimen = {key: assignment[key] for key in ("dose_quantity", "dose_unit", "frequency_per_day", "timing_instructions", "conditions")}
            adapter = ClaudeUsageAdapter() if current_app.config.get("USAGE_INFERENCE_PROVIDER") == "claude" else None
            assessment = validate_assessment(assess_usage(report_data, regimen, assignment["instruction_text"], adapter))
            assessment_id = clinical_store.save_assessment(report_id, assessment)
            draft = suggest_improvement(assignment["instruction_text"], assessment, regimen)
            if draft:
                clinical_store.create_suggestion(assessment_id, draft["proposed_wording"], draft["rationale"])
        except (ValueError, TypeError) as exc:
            flash(str(exc) or "Check the report fields.", "error")
        except PermissionError:
            abort(404)
        else:
            flash("Your actual-use report was recorded and compared with the approved documentation.", "success")
            return redirect(url_for("clinical.patient_report_detail", report_id=report_id))
    return render_template("patient_report_form.html", assignments=assignments, selected=selected, today=date.today().isoformat(), active="patient")


@bp.get("/patient/reports/<int:report_id>")
@role_required("patient")
def patient_report_detail(report_id: int):
    report = clinical_store.get_report(report_id)
    if not report or report["patient_id"] != g.user["id"]:
        abort(404)
    return render_template("patient_report_detail.html", report=report, active="patient")


@bp.post("/patient/clarification")
@role_required("patient")
def clarification():
    message = request.form.get("message", "").strip()
    try:
        assignment_id = int(request.form.get("assignment_id", ""))
        if not message or len(message) > 2000:
            raise ValueError
        clinical_store.create_clarification(g.user["id"], assignment_id, message)
    except (ValueError, PermissionError):
        flash("Enter a short clarification request for one of your assignments.", "error")
    else:
        flash("Your clarification request was recorded for the clinician.", "success")
    return redirect(url_for("clinical.patient_dashboard"))
