import hashlib

from werkzeug.security import generate_password_hash

from webapp import clinical_store


def test_clinician_and_patient_login_redirect_to_role_dashboard(client, login):
    response = login(client, "clinician@demo.test", "DemoClinician!2026")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/clinician")

    client.get("/logout")  # GET cannot mutate or sign out
    with client.session_transaction() as session:
        token = session["csrf_token"]
    client.post("/logout", data={"csrf_token": token})

    response = login(client, "alex.patient@demo.test", "DemoPatient!2026")
    assert response.headers["Location"].endswith("/patient")


def test_role_routes_and_csrf_are_enforced(client, login):
    login(client, "alex.patient@demo.test", "DemoPatient!2026")
    assert client.get("/clinician").status_code == 403
    assert client.get("/document-testing").status_code == 403
    assert client.post("/patient/clarification", data={"assignment_id": "1", "message": "test"}).status_code == 400


def test_patient_cannot_guess_other_patients_assignment_or_report(client, login):
    alex = clinical_store.get_user_by_email("alex.patient@demo.test")
    sam = clinical_store.get_user_by_email("sam.patient@demo.test")
    sam_assignment = clinical_store.list_assignments(sam["id"], True)[0]
    sam_report = clinical_store.list_reports_for_patient(sam["id"])[0]
    login(client, alex["email"], "DemoPatient!2026")
    assert client.get(f"/patient/assignments/{sam_assignment['id']}").status_code == 404
    assert client.get(f"/patient/assignments/{sam_assignment['id']}/download").status_code == 404
    assert client.get(f"/patient/reports/{sam_report['id']}").status_code == 404


def test_patient_can_read_summary_and_download_exact_approved_document(client, login):
    alex = clinical_store.get_user_by_email("alex.patient@demo.test")
    assignment = clinical_store.list_assignments(alex["id"], True)[0]
    login(client, alex["email"], "DemoPatient!2026")

    page = client.get(f"/patient/assignments/{assignment['id']}")
    assert page.status_code == 200
    assert b"What this document says" in page.data
    assert b"Document record" not in page.data

    download = client.get(f"/patient/assignments/{assignment['id']}/download")
    assert download.status_code == 200
    assert download.data.decode() == assignment["instruction_text"]
    assert "attachment" in download.headers["Content-Disposition"]
    assert f"v{assignment['version_number']}.txt" in download.headers["Content-Disposition"]


def test_clinician_cannot_access_unassigned_patient(client, login):
    clinician = clinical_store.get_user_by_email("clinician@demo.test")
    with clinical_store._connect() as conn:
        timestamp = clinical_store.now()
        org_id = conn.execute("INSERT INTO organisations (name, created_at) VALUES ('Other demo', ?)", (timestamp,)).lastrowid
        outsider_id = conn.execute(
            "INSERT INTO users (email, password_hash, role, organisation_id, display_name, created_at) VALUES (?, ?, 'patient', ?, ?, ?)",
            ("outside.patient@demo.test", generate_password_hash("OutsidePatient!2026"), org_id, "Outside Patient", timestamp),
        ).lastrowid
    login(client, clinician["email"], "DemoClinician!2026")
    assert client.get(f"/clinician/patients/{outsider_id}").status_code == 404


def test_invitation_token_is_hashed_single_use_and_activates_patient(client, login, csrf):
    clinician = clinical_store.get_user_by_email("clinician@demo.test")
    invitation_id, token = clinical_store.create_invitation(clinician["id"], "new.patient@demo.test", hours=1)
    with clinical_store._connect() as conn:
        row = conn.execute("SELECT * FROM invitations WHERE id = ?", (invitation_id,)).fetchone()
        assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
        assert token not in row["token_hash"]

    response = client.get(f"/activate/{token}")
    activation_csrf = csrf_from_response(response)
    response = client.post(
        f"/activate/{token}",
        data={
            "csrf_token": activation_csrf,
            "display_name": "New Fictional Patient",
            "password": "NewPatient!2026",
            "password_confirm": "NewPatient!2026",
        },
    )
    assert response.status_code == 302
    patient = clinical_store.get_user_by_email("new.patient@demo.test")
    assert patient and clinical_store.clinician_can_access(clinician["id"], patient["id"])
    try:
        clinical_store.accept_invitation(token, "AnotherPatient!2026", "Again")
    except ValueError:
        pass
    else:
        raise AssertionError("single-use invitation was accepted twice")


def csrf_from_response(response):
    import re
    return re.search(rb'name="csrf_token" value="([^"]+)"', response.data).group(1).decode()
