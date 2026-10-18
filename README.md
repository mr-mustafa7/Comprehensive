# Comprehensive

SotonShip 2026 · Responsible AI · Barclays Eagle Labs, Southampton

Patients leave with approved medication instructions and no easy way to say what they actually did. Comprehensive is a clinician-supervised workspace for that gap. A patient reports what they took, including when they are unsure. The report is compared with the exact regimen and document version their clinician approved. Only that clinician can judge the difference, or approve clearer wording.

Fictional patients and a fictional medicine only. This is a hackathon prototype, not medical advice, and not for treatment decisions.

## The problem

Take-home instructions can be factually right and still be followed differently. A patient may take the wrong number of doses, miss a condition, or not remember. A readability score does not catch that. Reversing an instruction barely changes how hard the sentence is to read, so every leaflet can look equally “too hard” whether or not the meaning is dangerous.

The clinician usually never sees the patient’s account next to the version they were given. If the wording is unclear, editing the original document also erases the record of what that patient was told.

## How it works

1. **Assign.** The clinician attaches one approved document version and one regimen to a patient. Dose, frequency, timing, and conditions are stored with that version.
2. **Report.** The patient records what they took. Uncertainty is an allowed answer, so they are not pushed to guess.
3. **Compare.** The structured regimen is the source of truth. Quantity, frequency, missing fields, and contradictions with the written account are checked with fixed rules. An optional language-model pass may add findings from the patient’s own words. It cannot invent a dose or rewrite an instruction. If that pass fails, the result is marked incomplete and sent for review, never treated as a match.
4. **Review.** The patient sees their report beside the approved wording, with a note to contact their clinician rather than change what they take. The clinician sees the evidence and must confirm, dismiss, or amend the assessment, with a reason.
5. **Improve.** A wording suggestion stays a suggestion until the clinician edits and approves it. Approval creates a new document version and a new assignment. The previous version, and every report linked to it, stay unchanged.

Each report keeps the assignment, regimen, and document-version ids that were active when it was submitted. Later approvals cannot rewrite that history.

Access is split by role. A patient sees only their own medicines and reports. A clinician sees only assigned patients. State-changing requests require a CSRF token. Invitations and passwords are stored as hashes. The local demo uses SQLite. A hosted demo uses PostgreSQL so the same reports remain after a redeploy.

## Try the demo

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m webapp.app
```

Open http://localhost:5050.

| Role | Email | Password |
|---|---|---|
| Clinician | `clinician@demo.test` | `DemoClinician!2026` |
| Patient, Alex Morgan | `alex.patient@demo.test` | `DemoPatient!2026` |

Sign in as Alex and submit a report for Medicine A. Sign in as the clinician, open the flagged report, and record a decision. Approving a wording suggestion should add a new document version and leave the original, and Alex’s report, where they were.
