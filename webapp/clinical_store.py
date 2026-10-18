"""SQLite persistence for the clinician/patient medication workflow.

The original ``runs`` and ``decisions`` tables remain owned by :mod:`webapp.store`.
These additive tables share the same database and use immutable version/assignment
links so historical reports always retain the instructions compared at the time.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from werkzeug.security import generate_password_hash

from src.usage_assessment import CLEAR_MESSAGE, INCOMPLETE_MESSAGE, REVIEW_MESSAGE
from webapp import store

SCHEMA = """
CREATE TABLE IF NOT EXISTS organisations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('clinician', 'patient')),
    organisation_id INTEGER NOT NULL REFERENCES organisations(id),
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clinician_patients (
    clinician_id INTEGER NOT NULL REFERENCES users(id),
    patient_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    PRIMARY KEY (clinician_id, patient_id)
);
CREATE TABLE IF NOT EXISTS invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_email TEXT NOT NULL COLLATE NOCASE,
    clinician_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    accepted_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS medication_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL,
    uploaded_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES medication_documents(id),
    version_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    approval_status TEXT NOT NULL CHECK(approval_status IN ('draft', 'approved', 'rejected')),
    approved_by INTEGER REFERENCES users(id),
    approved_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(document_id, version_number)
);
CREATE TABLE IF NOT EXISTS regimens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES users(id),
    document_id INTEGER NOT NULL REFERENCES medication_documents(id),
    medication_name TEXT NOT NULL,
    dose_quantity REAL NOT NULL CHECK(dose_quantity > 0),
    dose_unit TEXT NOT NULL,
    frequency_per_day INTEGER NOT NULL CHECK(frequency_per_day > 0),
    timing_instructions TEXT NOT NULL,
    conditions TEXT NOT NULL DEFAULT '',
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    approval_status TEXT NOT NULL CHECK(approval_status IN ('approved', 'inactive')),
    approved_by INTEGER NOT NULL REFERENCES users(id),
    approved_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES users(id),
    regimen_id INTEGER NOT NULL REFERENCES regimens(id),
    document_version_id INTEGER NOT NULL REFERENCES document_versions(id),
    assigned_by INTEGER NOT NULL REFERENCES users(id),
    assigned_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('active', 'superseded'))
);
CREATE TABLE IF NOT EXISTS usage_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id),
    patient_id INTEGER NOT NULL REFERENCES users(id),
    reported_usage_date TEXT NOT NULL,
    number_of_doses INTEGER,
    quantity_per_dose REAL,
    timing_information TEXT NOT NULL DEFAULT '',
    explanation TEXT NOT NULL DEFAULT '',
    uncertain INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES usage_reports(id),
    regimen_id INTEGER NOT NULL REFERENCES regimens(id),
    document_version_id INTEGER NOT NULL REFERENCES document_versions(id),
    status TEXT NOT NULL CHECK(status IN ('no_discrepancy_detected', 'review_required', 'analysis_incomplete')),
    structured_findings_json TEXT NOT NULL,
    cited_instruction TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_error TEXT,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assessment_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL REFERENCES ai_assessments(id),
    clinician_id INTEGER NOT NULL REFERENCES users(id),
    decision TEXT NOT NULL CHECK(decision IN ('confirmed', 'dismissed', 'amended')),
    amended_findings_json TEXT,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_version_id INTEGER NOT NULL REFERENCES document_versions(id),
    proposed_wording TEXT NOT NULL,
    rationale TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected')),
    reviewed_by INTEGER REFERENCES users(id),
    review_reason TEXT,
    reviewed_at TEXT,
    created_version_id INTEGER REFERENCES document_versions(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suggestion_assessments (
    suggestion_id INTEGER NOT NULL REFERENCES document_suggestions(id),
    assessment_id INTEGER NOT NULL REFERENCES ai_assessments(id),
    PRIMARY KEY (suggestion_id, assessment_id)
);
CREATE TABLE IF NOT EXISTS clarification_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES users(id),
    assignment_id INTEGER NOT NULL REFERENCES assignments(id),
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id INTEGER,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_relationship_patient ON clinician_patients(patient_id, status);
CREATE INDEX IF NOT EXISTS idx_assignments_patient ON assignments(patient_id, status);
CREATE INDEX IF NOT EXISTS idx_reports_patient ON usage_reports(patient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_assessments_report ON ai_assessments(report_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect():
    conn = store._connect()
    conn.executescript(SCHEMA)
    return conn


def init_db() -> None:
    with _connect():
        pass


def _dict(row) -> dict | None:
    return dict(row) if row else None


def audit(actor_id: int | None, action: str, record_type: str, record_id: int | None, details: dict | None = None, conn=None) -> None:
    owns = conn is None
    db = conn or _connect()
    db.execute(
        "INSERT INTO audit_events (actor_id, action, record_type, record_id, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (actor_id, action, record_type, record_id, json.dumps(details or {}, sort_keys=True), now()),
    )
    if owns:
        db.commit()
        db.close()


def get_user(user_id: int) -> dict | None:
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def get_user_by_email(email: str) -> dict | None:
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email.strip(),)).fetchone())


def create_user(email: str, password: str, role: str, organisation_id: int, display_name: str) -> int:
    if role not in {"clinician", "patient"}:
        raise ValueError("invalid role")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, role, organisation_id, display_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (email.strip().lower(), generate_password_hash(password), role, organisation_id, display_name.strip(), now()),
        )
        audit(cur.lastrowid, "user.created", "user", cur.lastrowid, {"role": role}, conn)
        return cur.lastrowid


def create_invitation(clinician_id: int, patient_email: str, hours: int = 48) -> tuple[int, str]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")
    with _connect() as conn:
        clinician = conn.execute("SELECT * FROM users WHERE id = ? AND role = 'clinician'", (clinician_id,)).fetchone()
        if not clinician:
            raise ValueError("clinician not found")
        if conn.execute("SELECT 1 FROM users WHERE lower(email) = lower(?)", (patient_email,)).fetchone():
            raise ValueError("an account already exists for that email")
        cur = conn.execute(
            "INSERT INTO invitations (patient_email, clinician_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (patient_email.strip().lower(), clinician_id, token_hash, expires, now()),
        )
        audit(clinician_id, "invitation.created", "invitation", cur.lastrowid, {"patient_email": patient_email.strip().lower()}, conn)
        return cur.lastrowid, token


def get_invitation_by_token(token: str) -> dict | None:
    digest = hashlib.sha256(token.encode()).hexdigest()
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM invitations WHERE token_hash = ?", (digest,)).fetchone())


def accept_invitation(token: str, password: str, display_name: str) -> int:
    digest = hashlib.sha256(token.encode()).hexdigest()
    timestamp = now()
    with _connect() as conn:
        invitation = conn.execute("SELECT * FROM invitations WHERE token_hash = ?", (digest,)).fetchone()
        if not invitation or invitation["accepted_at"] or invitation["expires_at"] <= timestamp:
            raise ValueError("invitation is invalid, expired, or already used")
        clinician = conn.execute("SELECT * FROM users WHERE id = ?", (invitation["clinician_id"],)).fetchone()
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, role, organisation_id, display_name, created_at) VALUES (?, ?, 'patient', ?, ?, ?)",
            (invitation["patient_email"], generate_password_hash(password), clinician["organisation_id"], display_name.strip(), timestamp),
        )
        patient_id = cur.lastrowid
        conn.execute(
            "INSERT INTO clinician_patients (clinician_id, patient_id, status, created_at) VALUES (?, ?, 'active', ?)",
            (invitation["clinician_id"], patient_id, timestamp),
        )
        conn.execute("UPDATE invitations SET accepted_at = ? WHERE id = ?", (timestamp, invitation["id"]))
        audit(patient_id, "invitation.accepted", "invitation", invitation["id"], {}, conn)
        return patient_id


def clinician_can_access(clinician_id: int, patient_id: int) -> bool:
    with _connect() as conn:
        return bool(conn.execute(
            "SELECT 1 FROM clinician_patients WHERE clinician_id = ? AND patient_id = ? AND status = 'active'",
            (clinician_id, patient_id),
        ).fetchone())


def list_patients(clinician_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT u.*, COUNT(DISTINCT a.id) AS assignment_count,
                      COUNT(DISTINCT CASE WHEN aa.status != 'no_discrepancy_detected' THEN ur.id END) AS review_count
               FROM clinician_patients cp JOIN users u ON u.id = cp.patient_id
               LEFT JOIN assignments a ON a.patient_id = u.id AND a.status = 'active'
               LEFT JOIN usage_reports ur ON ur.patient_id = u.id
               LEFT JOIN ai_assessments aa ON aa.report_id = ur.id
               WHERE cp.clinician_id = ? AND cp.status = 'active'
               GROUP BY u.id ORDER BY u.display_name""",
            (clinician_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_document(clinician_id: int, title: str, source: str, provenance: str, text: str) -> tuple[int, int]:
    timestamp = now()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO medication_documents (title, source, provenance, uploaded_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (title.strip(), source.strip(), provenance.strip(), clinician_id, timestamp),
        )
        document_id = cur.lastrowid
        version = conn.execute(
            """INSERT INTO document_versions
               (document_id, version_number, text, approval_status, approved_by, approved_at, created_at)
               VALUES (?, 1, ?, 'approved', ?, ?, ?)""",
            (document_id, text.strip(), clinician_id, timestamp, timestamp),
        ).lastrowid
        audit(clinician_id, "document.created", "medication_document", document_id, {"version_id": version}, conn)
        return document_id, version


def list_documents(clinician_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT d.*, COUNT(dv.id) AS version_count,
                      MAX(CASE WHEN dv.approval_status = 'approved' THEN dv.version_number END) AS latest_approved_version
               FROM medication_documents d JOIN users u ON u.id = d.uploaded_by
               LEFT JOIN document_versions dv ON dv.document_id = d.id
               WHERE u.organisation_id = (SELECT organisation_id FROM users WHERE id = ?)
               GROUP BY d.id ORDER BY d.created_at DESC""",
            (clinician_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_approved_versions(clinician_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT dv.id, dv.document_id, dv.version_number, dv.text, d.title
               FROM document_versions dv JOIN medication_documents d ON d.id = dv.document_id
               JOIN users u ON u.id = d.uploaded_by
               WHERE dv.approval_status = 'approved'
                 AND u.organisation_id = (SELECT organisation_id FROM users WHERE id = ?)
               ORDER BY d.title, dv.version_number DESC""",
            (clinician_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_document(document_id: int, clinician_id: int) -> dict | None:
    with _connect() as conn:
        doc = conn.execute(
            """SELECT d.* FROM medication_documents d JOIN users u ON u.id = d.uploaded_by
               WHERE d.id = ? AND u.organisation_id = (SELECT organisation_id FROM users WHERE id = ?)""",
            (document_id, clinician_id),
        ).fetchone()
        if not doc:
            return None
        result = dict(doc)
        result["versions"] = [dict(r) for r in conn.execute(
            """SELECT dv.*, u.display_name AS approver_name FROM document_versions dv
               LEFT JOIN users u ON u.id = dv.approved_by WHERE dv.document_id = ? ORDER BY dv.version_number DESC""",
            (document_id,),
        ).fetchall()]
        return result


def assign_regimen(clinician_id: int, patient_id: int, document_version_id: int, medication_name: str,
                   dose_quantity: float, dose_unit: str, frequency_per_day: int,
                   timing_instructions: str, conditions: str, effective_from: str) -> int:
    if not clinician_can_access(clinician_id, patient_id):
        raise PermissionError("patient is not assigned to this clinician")
    timestamp = now()
    with _connect() as conn:
        version = conn.execute(
            """SELECT dv.*, d.id AS document_id FROM document_versions dv
               JOIN medication_documents d ON d.id = dv.document_id JOIN users u ON u.id = d.uploaded_by
               WHERE dv.id = ? AND dv.approval_status = 'approved'
                 AND u.organisation_id = (SELECT organisation_id FROM users WHERE id = ?)""",
            (document_version_id, clinician_id),
        ).fetchone()
        if not version:
            raise ValueError("approved document version not found")
        regimen_id = conn.execute(
            """INSERT INTO regimens
               (patient_id, document_id, medication_name, dose_quantity, dose_unit, frequency_per_day,
                timing_instructions, conditions, effective_from, approval_status, approved_by, approved_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?)""",
            (patient_id, version["document_id"], medication_name.strip(), dose_quantity, dose_unit.strip(),
             frequency_per_day, timing_instructions.strip(), conditions.strip(), effective_from, clinician_id,
             timestamp, timestamp),
        ).lastrowid
        conn.execute("UPDATE assignments SET status = 'superseded', ended_at = ? WHERE patient_id = ? AND status = 'active' AND regimen_id IN (SELECT id FROM regimens WHERE document_id = ?)",
                     (timestamp, patient_id, version["document_id"]))
        assignment_id = conn.execute(
            "INSERT INTO assignments (patient_id, regimen_id, document_version_id, assigned_by, assigned_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
            (patient_id, regimen_id, document_version_id, clinician_id, timestamp),
        ).lastrowid
        audit(clinician_id, "assignment.created", "assignment", assignment_id, {"patient_id": patient_id, "regimen_id": regimen_id}, conn)
        return assignment_id


ASSIGNMENT_SELECT = """SELECT a.*, r.medication_name, r.dose_quantity, r.dose_unit,
 r.frequency_per_day, r.timing_instructions, r.conditions, r.effective_from, r.effective_to,
 d.id AS document_id, d.title AS document_title, d.source, d.provenance,
 dv.version_number, dv.text AS instruction_text, dv.approval_status AS version_approval_status
 FROM assignments a JOIN regimens r ON r.id = a.regimen_id
 JOIN document_versions dv ON dv.id = a.document_version_id
 JOIN medication_documents d ON d.id = dv.document_id"""


def get_assignment(assignment_id: int) -> dict | None:
    with _connect() as conn:
        return _dict(conn.execute(ASSIGNMENT_SELECT + " WHERE a.id = ?", (assignment_id,)).fetchone())


def list_assignments(patient_id: int, active_only: bool = False) -> list[dict]:
    where = " WHERE a.patient_id = ?" + (" AND a.status = 'active'" if active_only else "")
    with _connect() as conn:
        rows = conn.execute(ASSIGNMENT_SELECT + where + " ORDER BY a.assigned_at DESC", (patient_id,)).fetchall()
    return [dict(r) for r in rows]


def create_report(patient_id: int, assignment_id: int, reported_usage_date: str,
                  number_of_doses: int | None, quantity_per_dose: float | None,
                  timing_information: str, explanation: str, uncertain: bool) -> int:
    timestamp = now()
    with _connect() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ? AND patient_id = ? AND status = 'active'", (assignment_id, patient_id)).fetchone()
        if not assignment:
            raise PermissionError("assignment not found")
        report_id = conn.execute(
            """INSERT INTO usage_reports
               (assignment_id, patient_id, reported_usage_date, number_of_doses, quantity_per_dose,
                timing_information, explanation, uncertain, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (assignment_id, patient_id, reported_usage_date, number_of_doses, quantity_per_dose,
             timing_information.strip(), explanation.strip(), int(uncertain), timestamp),
        ).lastrowid
        audit(patient_id, "usage_report.created", "usage_report", report_id, {"assignment_id": assignment_id}, conn)
        return report_id


def save_assessment(report_id: int, assessment: dict) -> int:
    with _connect() as conn:
        report = conn.execute("SELECT ur.*, a.regimen_id, a.document_version_id FROM usage_reports ur JOIN assignments a ON a.id = ur.assignment_id WHERE ur.id = ?", (report_id,)).fetchone()
        if not report:
            raise ValueError("report not found")
        assessment_id = conn.execute(
            """INSERT INTO ai_assessments
               (report_id, regimen_id, document_version_id, status, structured_findings_json, cited_instruction,
                model_name, model_error, latency_ms, cost_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (report_id, report["regimen_id"], report["document_version_id"], assessment["status"],
             json.dumps(assessment), assessment.get("approved_instruction_excerpt", ""), assessment.get("model_name", "unknown"),
             assessment.get("model_error") or None, assessment.get("latency_ms", 0), assessment.get("cost_usd", 0.0), now()),
        ).lastrowid
        audit(report["patient_id"], "assessment.created", "ai_assessment", assessment_id, {"status": assessment["status"]}, conn)
        return assessment_id


REPORT_SELECT = """SELECT ur.*, a.regimen_id, a.document_version_id, a.assigned_by,
 r.medication_name, r.dose_quantity, r.dose_unit, r.frequency_per_day, r.timing_instructions, r.conditions,
 dv.version_number, dv.text AS instruction_text, d.title AS document_title,
 aa.id AS assessment_id, aa.status AS assessment_status, aa.structured_findings_json, aa.model_name,
 aa.model_error, aa.latency_ms, aa.cost_usd, aa.created_at AS assessed_at,
 (SELECT ar.decision FROM assessment_reviews ar WHERE ar.assessment_id = aa.id ORDER BY ar.id DESC LIMIT 1) AS review_decision,
 (SELECT ar.reason FROM assessment_reviews ar WHERE ar.assessment_id = aa.id ORDER BY ar.id DESC LIMIT 1) AS review_reason
 FROM usage_reports ur JOIN assignments a ON a.id = ur.assignment_id
 JOIN regimens r ON r.id = a.regimen_id JOIN document_versions dv ON dv.id = a.document_version_id
 JOIN medication_documents d ON d.id = dv.document_id
 LEFT JOIN ai_assessments aa ON aa.id = (SELECT id FROM ai_assessments x WHERE x.report_id = ur.id ORDER BY x.id DESC LIMIT 1)"""


def _report_dict(row) -> dict | None:
    if not row:
        return None
    result = dict(row)
    result["assessment"] = json.loads(result.pop("structured_findings_json")) if result.get("structured_findings_json") else None
    return result


def get_report(report_id: int) -> dict | None:
    with _connect() as conn:
        return _report_dict(conn.execute(REPORT_SELECT + " WHERE ur.id = ?", (report_id,)).fetchone())


def list_reports_for_patient(patient_id: int, limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(REPORT_SELECT + " WHERE ur.patient_id = ? ORDER BY ur.created_at DESC LIMIT ?", (patient_id, limit)).fetchall()
    return [_report_dict(r) for r in rows]


def list_reports_for_clinician(clinician_id: int, limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            REPORT_SELECT + " JOIN clinician_patients cp ON cp.patient_id = ur.patient_id AND cp.status = 'active' WHERE cp.clinician_id = ? ORDER BY ur.created_at DESC LIMIT ?",
            (clinician_id, limit),
        ).fetchall()
    return [_report_dict(r) for r in rows]


def create_suggestion(assessment_id: int, proposed_wording: str, rationale: str) -> int:
    with _connect() as conn:
        assessment = conn.execute("SELECT * FROM ai_assessments WHERE id = ?", (assessment_id,)).fetchone()
        if not assessment:
            raise ValueError("assessment not found")
        existing = conn.execute("SELECT suggestion_id FROM suggestion_assessments WHERE assessment_id = ?", (assessment_id,)).fetchone()
        if existing:
            return existing["suggestion_id"]
        suggestion_id = conn.execute(
            "INSERT INTO document_suggestions (document_version_id, proposed_wording, rationale, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (assessment["document_version_id"], proposed_wording.strip(), rationale.strip(), now()),
        ).lastrowid
        conn.execute("INSERT INTO suggestion_assessments (suggestion_id, assessment_id) VALUES (?, ?)", (suggestion_id, assessment_id))
        audit(None, "suggestion.created", "document_suggestion", suggestion_id, {"assessment_id": assessment_id}, conn)
        return suggestion_id


def list_suggestions(clinician_id: int, status: str | None = None) -> list[dict]:
    params: list[Any] = [clinician_id]
    filter_sql = ""
    if status:
        filter_sql = " AND ds.status = ?"
        params.append(status)
    with _connect() as conn:
        rows = conn.execute(
            """SELECT ds.*, d.title AS document_title, dv.version_number AS source_version,
                      COUNT(sa.assessment_id) AS assessment_count
               FROM document_suggestions ds JOIN document_versions dv ON dv.id = ds.document_version_id
               JOIN medication_documents d ON d.id = dv.document_id JOIN users u ON u.id = d.uploaded_by
               LEFT JOIN suggestion_assessments sa ON sa.suggestion_id = ds.id
               WHERE u.organisation_id = (SELECT organisation_id FROM users WHERE id = ?)""" + filter_sql +
            " GROUP BY ds.id ORDER BY ds.created_at DESC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_suggestion(suggestion_id: int, clinician_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            """SELECT ds.*, dv.text AS original_text, dv.version_number AS source_version,
                      d.id AS document_id, d.title AS document_title
               FROM document_suggestions ds JOIN document_versions dv ON dv.id = ds.document_version_id
               JOIN medication_documents d ON d.id = dv.document_id JOIN users u ON u.id = d.uploaded_by
               WHERE ds.id = ? AND u.organisation_id = (SELECT organisation_id FROM users WHERE id = ?)""",
            (suggestion_id, clinician_id),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["assessments"] = [dict(r) for r in conn.execute(
            """SELECT aa.id, aa.status, aa.report_id, ur.patient_id, u.display_name AS patient_name,
                      aa.structured_findings_json FROM suggestion_assessments sa
               JOIN ai_assessments aa ON aa.id = sa.assessment_id JOIN usage_reports ur ON ur.id = aa.report_id
               JOIN users u ON u.id = ur.patient_id WHERE sa.suggestion_id = ?""",
            (suggestion_id,),
        ).fetchall()]
        for assessment in result["assessments"]:
            assessment["findings"] = json.loads(assessment.pop("structured_findings_json"))["findings"]
        return result


def review_suggestion(suggestion_id: int, clinician_id: int, action: str, wording: str, reason: str) -> int | None:
    if action not in {"approve", "reject"}:
        raise ValueError("invalid action")
    timestamp = now()
    with _connect() as conn:
        suggestion = conn.execute(
            """SELECT ds.*, dv.document_id FROM document_suggestions ds
               JOIN document_versions dv ON dv.id = ds.document_version_id
               JOIN medication_documents d ON d.id = dv.document_id JOIN users u ON u.id = d.uploaded_by
               WHERE ds.id = ? AND ds.status = 'pending'
                 AND u.organisation_id = (SELECT organisation_id FROM users WHERE id = ?)""",
            (suggestion_id, clinician_id),
        ).fetchone()
        if not suggestion:
            raise ValueError("pending suggestion not found")
        created_version_id = None
        status = "approved" if action == "approve" else "rejected"
        if action == "approve":
            if not wording.strip():
                raise ValueError("approved wording is required")
            next_version = conn.execute("SELECT COALESCE(MAX(version_number), 0) + 1 FROM document_versions WHERE document_id = ?", (suggestion["document_id"],)).fetchone()[0]
            created_version_id = conn.execute(
                """INSERT INTO document_versions
                   (document_id, version_number, text, approval_status, approved_by, approved_at, created_at)
                   VALUES (?, ?, ?, 'approved', ?, ?, ?)""",
                (suggestion["document_id"], next_version, wording.strip(), clinician_id, timestamp, timestamp),
            ).lastrowid
            # Assign the approved supplementary wording to every active assignment
            # that still uses the source version. Old assignment rows remain immutable.
            assignments = conn.execute("SELECT * FROM assignments WHERE document_version_id = ? AND status = 'active'", (suggestion["document_version_id"],)).fetchall()
            for assignment in assignments:
                conn.execute("UPDATE assignments SET status = 'superseded', ended_at = ? WHERE id = ?", (timestamp, assignment["id"]))
                conn.execute(
                    "INSERT INTO assignments (patient_id, regimen_id, document_version_id, assigned_by, assigned_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
                    (assignment["patient_id"], assignment["regimen_id"], created_version_id, clinician_id, timestamp),
                )
        conn.execute(
            """UPDATE document_suggestions SET proposed_wording = ?, status = ?, reviewed_by = ?,
               review_reason = ?, reviewed_at = ?, created_version_id = ? WHERE id = ?""",
            (wording.strip() or suggestion["proposed_wording"], status, clinician_id, reason.strip(), timestamp, created_version_id, suggestion_id),
        )
        audit(clinician_id, f"suggestion.{status}", "document_suggestion", suggestion_id, {"created_version_id": created_version_id}, conn)
        return created_version_id


def review_assessment(assessment_id: int, clinician_id: int, decision: str, reason: str, amended_findings: str = "") -> int:
    if decision not in {"confirmed", "dismissed", "amended"}:
        raise ValueError("invalid decision")
    with _connect() as conn:
        assessment = conn.execute(
            """SELECT aa.* FROM ai_assessments aa JOIN usage_reports ur ON ur.id = aa.report_id
               JOIN clinician_patients cp ON cp.patient_id = ur.patient_id AND cp.status = 'active'
               WHERE aa.id = ? AND cp.clinician_id = ?""",
            (assessment_id, clinician_id),
        ).fetchone()
        if not assessment:
            raise PermissionError("assessment not found")
        amended_json = None
        if decision == "amended":
            amended_json = json.dumps({"clinician_amendment": amended_findings.strip()})
        review_id = conn.execute(
            """INSERT INTO assessment_reviews
               (assessment_id, clinician_id, decision, amended_findings_json, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (assessment_id, clinician_id, decision, amended_json, reason.strip(), now()),
        ).lastrowid
        audit(clinician_id, "assessment.reviewed", "assessment_review", review_id, {"decision": decision}, conn)
        return review_id


def create_clarification(patient_id: int, assignment_id: int, message: str) -> int:
    with _connect() as conn:
        if not conn.execute("SELECT 1 FROM assignments WHERE id = ? AND patient_id = ?", (assignment_id, patient_id)).fetchone():
            raise PermissionError("assignment not found")
        request_id = conn.execute(
            "INSERT INTO clarification_requests (patient_id, assignment_id, message, created_at) VALUES (?, ?, ?, ?)",
            (patient_id, assignment_id, message.strip(), now()),
        ).lastrowid
        audit(patient_id, "clarification.requested", "clarification_request", request_id, {}, conn)
        return request_id


def recent_audit(clinician_id: int, limit: int = 12) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT ae.*, u.display_name AS actor_name FROM audit_events ae LEFT JOIN users u ON u.id = ae.actor_id
               WHERE u.organisation_id = (SELECT organisation_id FROM users WHERE id = ?) OR ae.actor_id IS NULL
               ORDER BY ae.id DESC LIMIT ?""",
            (clinician_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def count_open_clarifications(clinician_id: int) -> int:
    with _connect() as conn:
        return conn.execute(
            """SELECT COUNT(*) FROM clarification_requests cr JOIN clinician_patients cp ON cp.patient_id = cr.patient_id
               WHERE cp.clinician_id = ? AND cp.status = 'active' AND cr.status = 'open'""",
            (clinician_id,),
        ).fetchone()[0]


def seed_demo_data() -> dict:
    """Idempotently create the sample organisation and accounts."""
    init_db()
    with _connect() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email = 'clinician@demo.test'").fetchone()
        if existing:
            conn.execute("UPDATE organisations SET name = 'Comprehensive Clinic' WHERE name = 'Comprehensive Demo Clinic'")
            conn.execute(
                """UPDATE medication_documents
                   SET source = 'Clinician-authored supplementary documentation',
                       provenance = 'Clinician-authored; not a manufacturer leaflet'
                   WHERE source = 'Fictional clinician-authored demo'""",
            )
            conn.execute(
                """UPDATE regimens SET conditions = 'Contact the clinic if the written documentation is unclear.'
                   WHERE conditions = 'Contact the fictional demo clinic if the written documentation is unclear.'""",
            )
            conn.execute(
                """UPDATE document_suggestions
                   SET rationale = 'Clinician-approved supplementary wording.'
                   WHERE rationale = 'Clinician-approved supplementary wording for the synthetic demo.'""",
            )
            conn.execute("UPDATE audit_events SET action = 'workspace.seeded' WHERE action = 'demo.seeded'")
            invite_hash = hashlib.sha256(b"demo-activate-fictional-patient-2026").hexdigest()
            if not conn.execute("SELECT 1 FROM invitations WHERE token_hash = ?", (invite_hash,)).fetchone():
                expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec="seconds")
                conn.execute(
                    "INSERT INTO invitations (patient_email, clinician_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("invited.patient@demo.test", existing["id"], invite_hash, expires, now()),
                )
            return {"clinician_id": existing["id"]}
        timestamp = now()
        org_id = conn.execute("INSERT INTO organisations (name, created_at) VALUES ('Comprehensive Clinic', ?)", (timestamp,)).lastrowid
        clinician_id = conn.execute(
            "INSERT INTO users (email, password_hash, role, organisation_id, display_name, created_at) VALUES (?, ?, 'clinician', ?, ?, ?)",
            ("clinician@demo.test", generate_password_hash("DemoClinician!2026"), org_id, "Dr Mustafa Alhadad", timestamp),
        ).lastrowid
        invite_hash = hashlib.sha256(b"demo-activate-fictional-patient-2026").hexdigest()
        conn.execute(
            "INSERT INTO invitations (patient_email, clinician_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            ("invited.patient@demo.test", clinician_id, invite_hash,
             (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec="seconds"), timestamp),
        )
        patients = []
        for email, name in [("alex.patient@demo.test", "Alex Morgan"), ("sam.patient@demo.test", "Sam Taylor")]:
            patient_id = conn.execute(
                "INSERT INTO users (email, password_hash, role, organisation_id, display_name, created_at) VALUES (?, ?, 'patient', ?, ?, ?)",
                (email, generate_password_hash("DemoPatient!2026"), org_id, name, timestamp),
            ).lastrowid
            conn.execute("INSERT INTO clinician_patients VALUES (?, ?, 'active', ?)", (clinician_id, patient_id, timestamp))
            patients.append(patient_id)
        document_id = conn.execute(
            "INSERT INTO medication_documents (title, source, provenance, uploaded_by, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Medicine A — supplementary documentation", "Clinician-authored supplementary documentation", "Clinician-authored; not a manufacturer's leaflet", clinician_id, timestamp),
        ).lastrowid
        v1 = conn.execute(
            """INSERT INTO document_versions
               (document_id, version_number, text, approval_status, approved_by, approved_at, created_at)
               VALUES (?, 1, ?, 'approved', ?, ?, ?)""",
            (document_id, "Take one tablet once daily.", clinician_id, timestamp, timestamp),
        ).lastrowid
        v2 = conn.execute(
            """INSERT INTO document_versions
               (document_id, version_number, text, approval_status, approved_by, approved_at, created_at)
               VALUES (?, 2, ?, 'approved', ?, ?, ?)""",
            (document_id, "Take one tablet once per day, in the morning at the time agreed with your clinician. Do not take an additional dose.", clinician_id, timestamp, timestamp),
        ).lastrowid
        assignments = []
        for index, patient_id in enumerate(patients):
            regimen_id = conn.execute(
                """INSERT INTO regimens
                   (patient_id, document_id, medication_name, dose_quantity, dose_unit, frequency_per_day,
                    timing_instructions, conditions, effective_from, approval_status, approved_by, approved_at, created_at)
                   VALUES (?, ?, 'Medicine A', 1, 'tablet', 1, 'in the morning at the time agreed with your clinician',
                           'Contact the clinic if the written documentation is unclear.', '2026-10-01',
                           'approved', ?, ?, ?)""",
                (patient_id, document_id, clinician_id, timestamp, timestamp),
            ).lastrowid
            version = v1 if index == 0 else v2
            assignment_id = conn.execute(
                "INSERT INTO assignments (patient_id, regimen_id, document_version_id, assigned_by, assigned_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
                (patient_id, regimen_id, version, clinician_id, timestamp),
            ).lastrowid
            assignments.append((assignment_id, regimen_id, version))

        def seeded_report(patient_index, day, doses, quantity, timing, explanation, uncertain, status, types, summary, error=""):
            patient_id = patients[patient_index]
            assignment_id, regimen_id, version_id = assignments[patient_index]
            report_id = conn.execute(
                """INSERT INTO usage_reports
                   (assignment_id, patient_id, reported_usage_date, number_of_doses, quantity_per_dose,
                    timing_information, explanation, uncertain, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (assignment_id, patient_id, day, doses, quantity, timing, explanation, int(uncertain), timestamp),
            ).lastrowid
            instruction = conn.execute("SELECT text FROM document_versions WHERE id = ?", (version_id,)).fetchone()[0]
            findings = [{
                "type": kind, "reported_value": str(doses), "approved_value": "1 dose per day",
                "evidence": summary, "requires_clinician_review": True,
            } for kind in types]
            payload = {
                "status": status, "potential_discrepancy": bool(findings), "discrepancy_types": types,
                "patient_report_summary": f"{doses if doses is not None else 'unknown'} dose(s), {quantity if quantity is not None else 'unknown'} tablet each time",
                "approved_instruction_excerpt": instruction, "findings": findings,
                "patient_message": (
                    CLEAR_MESSAGE if status == "no_discrepancy_detected"
                    else INCOMPLETE_MESSAGE if status == "analysis_incomplete"
                    else REVIEW_MESSAGE
                ),
                "clinician_summary": summary, "analysis_complete": status != "analysis_incomplete",
                "model_name": "deterministic-usage-comparator-v1", "model_error": error, "latency_ms": 1, "cost_usd": 0.0,
            }
            assessment_id = conn.execute(
                """INSERT INTO ai_assessments
                   (report_id, regimen_id, document_version_id, status, structured_findings_json, cited_instruction,
                    model_name, model_error, latency_ms, cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)""",
                (report_id, regimen_id, version_id, status, json.dumps(payload), instruction,
                 "deterministic-usage-comparator-v1", error or None, timestamp),
            ).lastrowid
            return report_id, assessment_id

        seeded_report(0, "2026-10-15", 1, 1, "08:00", "I took one tablet in the morning.", False,
                      "no_discrepancy_detected", [], "Structured details match.")
        _, discrepancy_assessment = seeded_report(0, "2026-10-16", 2, 1, "08:00 and 20:00",
                      "I took one tablet in the morning and another at night.", False,
                      "review_required", ["frequency_mismatch"], "Reported twice; approved frequency is once per day.")
        seeded_report(1, "2026-10-16", None, None, "", "I cannot remember whether I took it.", True,
                      "analysis_incomplete", ["missing_information", "ambiguous_report"],
                      "The patient reported uncertainty and missing details.", "patient marked the report as uncertain")
        suggestion_id = conn.execute(
            """INSERT INTO document_suggestions
               (document_version_id, proposed_wording, rationale, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (v1, "Take one tablet once per day, at the time specified by your clinician.",
             "The frequency wording may be worth investigating after a reported difference; this does not establish causation.", timestamp),
        ).lastrowid
        conn.execute("INSERT INTO suggestion_assessments VALUES (?, ?)", (suggestion_id, discrepancy_assessment))
        approved_suggestion = conn.execute(
            """INSERT INTO document_suggestions
               (document_version_id, proposed_wording, rationale, status, reviewed_by, review_reason, reviewed_at, created_version_id, created_at)
               VALUES (?, ?, ?, 'approved', ?, ?, ?, ?, ?)""",
            (v1, "Take one tablet once per day, in the morning at the time agreed with your clinician. Do not take an additional dose.",
             "Clinician-approved supplementary wording.", clinician_id,
             "Approved as clearer supplementary documentation; regimen unchanged.", timestamp, v2, timestamp),
        ).lastrowid
        conn.execute("INSERT INTO suggestion_assessments VALUES (?, ?)", (approved_suggestion, discrepancy_assessment))
        audit(clinician_id, "workspace.seeded", "organisation", org_id, {"synthetic": True}, conn)
        return {"clinician_id": clinician_id, "patient_ids": patients, "document_id": document_id}
