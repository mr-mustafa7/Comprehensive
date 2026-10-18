# Comprehensive

Patients are handed approved medication instructions, then left to work out what they actually did. Comprehensive closes that gap: a patient reports what they took, the report is compared with the exact wording their clinician approved, and only that clinician can decide what the difference means or whether the documentation should change.

This is a hackathon prototype with fictional patients and a fictional medicine. It is not medical advice, and it is not for treatment decisions.

## The problem

Written instructions can be accurate and still be followed differently from how they were meant. A patient may take the wrong number of doses, miss a condition, or be unsure what happened. A readability score will not catch that: reversing an instruction barely changes how hard the sentence is to read.

Clinicians rarely see the report next to the version the patient was given. If the wording is unclear, editing the original document erases the record of what that patient was actually told.

## How it is solved

Each patient is assigned one approved document version and one regimen. A report is stored against those ids, so later edits cannot rewrite what was in force at the time.

Comparison starts from the structured regimen, not from a general leaflet. Quantity, frequency, missing fields, uncertainty, and contradictions with the free-text account are checked deterministically. An optional language-model pass may add findings from the patient's own words. It cannot invent a dose or change an instruction. If that pass fails, the result is incomplete and sent for review, never treated as a match.

The patient sees the report beside the approved wording, with a non-prescriptive note to contact their clinician. The clinician sees the evidence and must confirm, dismiss, or amend the assessment, with a reason. A suggested wording change stays a suggestion until the clinician edits and approves it. Approval creates a new document version and a new assignment. The previous version, and every report linked to it, stay as they were.

Sessions are role-scoped, state-changing requests require a CSRF token, and invitations and passwords are stored only as hashes. Locally the record is SQLite. A hosted demo uses PostgreSQL so the same history survives a redeploy.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m webapp.app
```

Open http://localhost:5050.

| Role | Email | Password |
|---|---|---|
| Clinician | `clinician@demo.test` | `DemoClinician!2026` |
| Patient | `alex.patient@demo.test` | `DemoPatient!2026` |

Sign in as Alex, report what was taken, then sign in as the clinician and review the flagged report. Approving a wording suggestion should leave the original version in the document history.
