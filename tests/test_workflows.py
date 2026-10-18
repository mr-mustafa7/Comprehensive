from datetime import date

from webapp import clinical_store


def session_csrf(client):
    with client.session_transaction() as session:
        return session["csrf_token"]


def test_document_assignment_and_audit_trail(client, login):
    login(client, "clinician@demo.test", "DemoClinician!2026")
    sam = clinical_store.get_user_by_email("sam.patient@demo.test")
    version = clinical_store.list_approved_versions(clinical_store.get_user_by_email("clinician@demo.test")["id"])[0]
    response = client.post(
        f"/clinician/patients/{sam['id']}/assign",
        data={
            "csrf_token": session_csrf(client), "document_version_id": version["id"],
            "medication_name": "Medicine A", "dose_quantity": "1", "dose_unit": "tablet",
            "frequency_per_day": "1", "timing_instructions": "in the morning",
            "conditions": "fictional demo only", "effective_from": "2026-10-18",
        },
    )
    assert response.status_code == 302
    active = clinical_store.list_assignments(sam["id"], True)
    assert active and active[0]["document_version_id"] == version["id"]
    assert any(e["action"] == "assignment.created" for e in clinical_store.recent_audit(clinical_store.get_user_by_email("clinician@demo.test")["id"], 50))


def test_patient_report_submission_creates_assessment_and_suggestion(client, login):
    alex = clinical_store.get_user_by_email("alex.patient@demo.test")
    assignment = clinical_store.list_assignments(alex["id"], True)[0]
    login(client, alex["email"], "DemoPatient!2026")
    response = client.post(
        "/patient/report",
        data={
            "csrf_token": session_csrf(client), "assignment_id": assignment["id"],
            "reported_usage_date": date.today().isoformat(), "number_of_doses": "2",
            "quantity_per_dose": "1", "timing_information": "morning and night",
            "explanation": "I took one in the morning and another at night.",
        },
    )
    assert response.status_code == 302
    latest = clinical_store.list_reports_for_patient(alex["id"])[0]
    assert latest["assessment_status"] == "review_required"
    assert "frequency_mismatch" in latest["assessment"]["discrepancy_types"]
    assert any(s["status"] == "pending" for s in clinical_store.list_suggestions(assignment["assigned_by"]))


def test_clinician_review_decision_is_persisted(client, login):
    clinician = clinical_store.get_user_by_email("clinician@demo.test")
    alex = clinical_store.get_user_by_email("alex.patient@demo.test")
    report = next(r for r in clinical_store.list_reports_for_patient(alex["id"]) if r["assessment_status"] == "review_required")
    login(client, clinician["email"], "DemoClinician!2026")
    response = client.post(
        f"/clinician/assessments/{report['assessment_id']}/review",
        data={"csrf_token": session_csrf(client), "decision": "confirmed", "reason": "Structured frequency differs from the approved regimen."},
    )
    assert response.status_code == 302
    reviewed = clinical_store.get_report(report["id"])
    assert reviewed["review_decision"] == "confirmed"
    assert any(e["action"] == "assessment.reviewed" for e in clinical_store.recent_audit(clinician["id"], 50))


def test_suggestion_approval_creates_new_version_without_overwriting_original(client, login):
    clinician = clinical_store.get_user_by_email("clinician@demo.test")
    suggestion = clinical_store.list_suggestions(clinician["id"], "pending")[0]
    detail = clinical_store.get_suggestion(suggestion["id"], clinician["id"])
    document_before = clinical_store.get_document(detail["document_id"], clinician["id"])
    original_text = next(v["text"] for v in document_before["versions"] if v["id"] == detail["document_version_id"])
    login(client, clinician["email"], "DemoClinician!2026")
    revised = "Take one tablet once per day, in the morning at the time agreed with your clinician."
    response = client.post(
        f"/clinician/suggestions/{suggestion['id']}/review",
        data={"csrf_token": session_csrf(client), "action": "approve", "wording": revised, "reason": "Clearer supplementary wording; regimen unchanged."},
    )
    assert response.status_code == 302
    document_after = clinical_store.get_document(detail["document_id"], clinician["id"])
    assert len(document_after["versions"]) == len(document_before["versions"]) + 1
    assert any(v["text"] == revised for v in document_after["versions"])
    assert any(v["text"] == original_text for v in document_after["versions"])


def test_patient_report_form_does_not_force_guessing_when_uncertain(client, login):
    sam = clinical_store.get_user_by_email("sam.patient@demo.test")
    assignment = clinical_store.list_assignments(sam["id"], True)[0]
    login(client, sam["email"], "DemoPatient!2026")
    response = client.post(
        "/patient/report",
        data={
            "csrf_token": session_csrf(client), "assignment_id": assignment["id"],
            "reported_usage_date": date.today().isoformat(), "number_of_doses": "",
            "quantity_per_dose": "", "timing_information": "", "explanation": "I cannot remember.",
            "uncertain": "1",
        },
    )
    assert response.status_code == 302
    report = clinical_store.list_reports_for_patient(sam["id"])[0]
    assert report["assessment_status"] == "analysis_incomplete"
