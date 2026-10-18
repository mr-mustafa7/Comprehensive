import re
from datetime import date

from webapp import clinical_store


def token_from(response):
    return re.search(rb'name="csrf_token" value="([^"]+)"', response.data).group(1).decode()


def login(client, email, password):
    token = token_from(client.get("/login"))
    return client.post("/login", data={"csrf_token": token, "email": email, "password": password})


def csrf(client):
    with client.session_transaction() as session:
        return session["csrf_token"]


def logout(client):
    client.post("/logout", data={"csrf_token": csrf(client)})


def test_complete_demo_journey(client):
    clinician = clinical_store.get_user_by_email("clinician@demo.test")
    alex = clinical_store.get_user_by_email("alex.patient@demo.test")

    assert login(client, clinician["email"], "DemoClinician!2026").headers["Location"].endswith("/clinician")
    assert client.get(f"/clinician/patients/{alex['id']}").status_code == 200
    logout(client)

    login(client, alex["email"], "DemoPatient!2026")
    assignment = clinical_store.list_assignments(alex["id"], True)[0]
    submitted = client.post(
        "/patient/report",
        data={
            "csrf_token": csrf(client), "assignment_id": assignment["id"],
            "reported_usage_date": date.today().isoformat(), "number_of_doses": "2",
            "quantity_per_dose": "1", "timing_information": "morning and night",
            "explanation": "I took one tablet in the morning and another at night.",
        },
    )
    assert submitted.status_code == 302
    report_url = submitted.headers["Location"]
    feedback = client.get(report_url)
    assert b"possible difference needs clinician review" in feedback.data
    assert b"Do not change what you take" in feedback.data
    report = clinical_store.list_reports_for_patient(alex["id"])[0]
    logout(client)

    login(client, clinician["email"], "DemoClinician!2026")
    assert client.get(f"/clinician/reports/{report['id']}").status_code == 200
    reviewed = client.post(
        f"/clinician/assessments/{report['assessment_id']}/review",
        data={"csrf_token": csrf(client), "decision": "confirmed", "reason": "The reported frequency differs from the approved regimen."},
    )
    assert reviewed.status_code == 302

    suggestion = clinical_store.list_suggestions(clinician["id"], "pending")[0]
    detail = clinical_store.get_suggestion(suggestion["id"], clinician["id"])
    assert client.get(f"/clinician/suggestions/{suggestion['id']}").status_code == 200
    wording = "Take one tablet once per day, in the morning at the time agreed with your clinician."
    approved = client.post(
        f"/clinician/suggestions/{suggestion['id']}/review",
        data={"csrf_token": csrf(client), "action": "approve", "wording": wording, "reason": "Approved as clearer supplementary wording; regimen unchanged."},
    )
    assert approved.status_code == 302
    history = client.get(f"/clinician/documents/{detail['document_id']}")
    assert wording.encode() in history.data
    assert detail["original_text"].encode() in history.data
