# Comprehensive 2.0

SotonShip 2026 · Responsible AI track · Barclays Eagle Labs Southampton

Comprehensive 2.0 is a clinician-supervised medication communication prototype.
Fictional patients report what they **actually took**; the application compares that
report with the exact approved patient-specific regimen and instruction version,
shows possible differences with evidence, and keeps a clinician in control of every
assessment and wording change.

> **Hackathon MVP only.** This repository uses fictional patients, a fictional
> “Medicine A”, and synthetic reports. It is not clinically validated, NHS-approved,
> GDPR-compliant, or suitable for treatment decisions. It must not be used with real
> patient data.

## Quick start and demo accounts

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export COMPREHENSIVE_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
.venv/bin/python -m webapp.app
```

Open <http://localhost:5050>. The first launch creates idempotent synthetic demo data
in `outputs/review.db` without changing the historical CSV evaluation outputs.

| Role | Email | Password |
|---|---|---|
| Fictional clinician | `clinician@demo.test` | `DemoClinician!2026` |
| Fictional patient Alex | `alex.patient@demo.test` | `DemoPatient!2026` |
| Fictional patient Sam | `sam.patient@demo.test` | `DemoPatient!2026` |

A seeded, single-use test activation URL is available at
`/activate/demo-activate-fictional-patient-2026` for
`invited.patient@demo.test` for 30 days after a clean seed. Normal invitations use
`secrets.token_urlsafe(32)`; only SHA-256 token hashes are stored.

Run the reproducible checks:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m src.usage_eval --write
```

The Claude-backed free-text adapter is optional in the reproducible offline demo.
Enable it only for synthetic data after authenticating the existing Claude Code CLI:

```bash
export COMPREHENSIVE_USAGE_MODEL=claude
npx -y @anthropic-ai/claude-code   # complete /login once
.venv/bin/python -m webapp.app
```

Without that environment setting, explicit quantity/frequency checks, uncertainty,
missing fields, and common structured/free-text contradictions run locally and
deterministically. With it enabled, `src/usage_assessment.py` sends only the
synthetic report and approved regimen to the existing `src/claude_cli.py` adapter
(`claude-cli:sonnet`). Model identifier, latency, CLI-reported cost, and errors are
stored. A transport or parse failure produces `analysis_incomplete`, never a clean
result.

## Demo journey

1. Sign in as `clinician@demo.test` and open **Alex Morgan**.
2. Inspect the immutable Medicine A regimen, instruction version, and seeded report
   history. The document library also shows the clinician-approved version 2.
3. Sign out and sign in as `alex.patient@demo.test`.
4. Choose **Report what I took**, enter two doses of one tablet (morning and night),
   and describe what actually happened.
5. Open the resulting patient feedback. It shows the report beside the approved
   wording, labels the possible frequency difference, and gives non-prescriptive
   contact guidance.
6. Return as the clinician. Open the flagged report, inspect its evidence, and
   confirm, dismiss, or amend the assessment with a recorded reason.
7. Open its wording suggestion. Edit and approve it to create a new immutable
   supplementary-instruction version; the old version and report link remain intact.
8. Open the document history and recent activity to see version, review, assignment,
   and audit lineage.
9. Use **Pre-release testing** to verify that the original simulated-reader panel,
   OCR upload, review queue, edit/retest, governance, and historical evaluation UI
   remain separate and available.

## Users, buyer, architecture, and data flow

The direct users are clinicians responsible for medication communication and
patients completing supervised follow-up. A credible buyer is an NHS trust or its
medication/discharge-software supplier purchasing a governed communication and
assurance workflow—not an autonomous prescribing tool.

The implementation deliberately retains Flask and SQLite:

```text
Patient report
  → immutable assignment (regimen + approved document version)
  → deterministic structured comparison
  → optional Claude free-text adapter
  → validated assessment (clean / review required / incomplete)
  → clinician decision + labelled feedback
  → optional wording suggestion
  → clinician-edited approval creates a new version and assignment
```

- `webapp/app.py` retains the original Flask routes and registers the new workflow.
- `webapp/clinical_store.py` adds normalised, foreign-keyed domain tables to the
  existing SQLite database. Queries are kept out of templates/routes so a later
  PostgreSQL repository adapter is straightforward.
- `webapp/security.py` provides server-side sessions, role decorators, CSRF checks,
  secure Werkzeug password hashes, and session-cookie settings.
- `src/usage_assessment.py` separates deterministic checks from the swappable
  inference adapter. It never invents or changes an instruction.
- `src/document_feedback.py` creates a clinician-review-only supplementary wording
  hypothesis. It never claims the document caused a patient's behaviour.

Every report points to the assignment, regimen, and document-version IDs active at
submission. New wording creates a new version and assignment instead of mutating
history. Assessment reviews provide Loop B labelled feedback; approved instruction
versions provide Loop A workflow improvement. Nothing retrains or fine-tunes model
weights automatically.

## Security, privacy, and limitations

The MVP enforces clinician/patient roles, relationship-scoped clinician access,
patient ownership checks, CSRF on every state-changing request, random expiring
single-use invitations, token hashing, password hashing, input validation, and an
append-only audit trail. The application intentionally returns 404 for guessed
patient records outside the authorised relationship.

These controls are appropriate for a hackathon demonstration, not production health
data. Real deployment would additionally require threat modelling and penetration
testing, managed secret rotation, TLS and secure-cookie enforcement, robust rate
limiting/MFA/SSO, encrypted backups, retention and deletion policies, data-protection
impact assessment, supplier and model-provider agreements, monitoring, incident
response, accessibility research, clinical safety cases, qualified clinical
validation, and regulatory assessment. No real patient information should be sent
to Claude or stored in this prototype.

## New usage-workflow evaluation

Development examples and held-out examples are separated under
`data/usage_assessment/`. `python -m src.usage_eval --write` evaluates the held-out
set and writes `outputs/usage_eval_results.json`; it does not touch or relabel the
original document-comprehension measurements.

On the current **8 hand-authored synthetic held-out examples** (6 expected review,
2 expected no-review), the rules-only quantity/frequency baseline recorded 3 true
positives, 3 missed discrepancies, 0 false alarms, and 2 true negatives. The hybrid
structured + text-safety comparator recorded 6 true positives, 0 misses, 0 false
alarms, and 2 true negatives. These exact numbers are reproducible and visible at
`/clinician/usage-evaluation`; the sample is far too small and artificial to support
any clinical or generalisation claim.

## Existing pre-release document-testing capability

The original application remains available as a distinct clinician-only feature.
Its historical datasets and result CSVs are unchanged. The remainder of this README
documents that original simulated-reader comprehension-gap checker and its previously
collected measurements. The original pipeline was built with Claude Code assistance,
as disclosed in its historical AI-disclosure section below. The Comprehensive 2.0
extension in this repository was implemented with OpenAI Codex as a software
engineering assistant; its generated changes were exercised by the automated suite
and browser smoke tests, but that does not constitute independent clinical review.

> We help an NHS AI-vendor building discharge-documentation tools (and the trust
> discharge-documentation leads who use them) catch likely misunderstandings in
> AI-drafted patient take-home instructions before they reach a patient, by
> scaling the "teach-back" check — an AHRQ/Joint Commission/NHS-endorsed
> technique proven to work when delivered live but constrained by scarce
> clinical time — to every document, using a simulated-reader panel and a
> misunderstanding-judge that a readability-score baseline cannot replicate.

**This is already happening, not hypothetical.** Chelsea and Westminster NHS
Foundation Trust began piloting an AI-assisted discharge-summary tool in August
2025 — built on the NHS Federated Data Platform, part of the government's AI
Exemplars programme — that drafts a discharge summary for a clinician to review
and sign off. Source:
[Digital Health News, 7 Aug 2025](https://www.digitalhealth.net/2025/08/ai-assisted-tool-on-fdp-will-help-write-hospital-discharge-letters/)
(accessed 2026-10-17). AI is drafting this content today. Nobody is yet checking
it for the specific failure mode of a technically-accurate instruction that a
patient will still misread.

**What the evidence actually supports — we checked hard, and corrected our own
pitch twice on this point.** We ran an adversarial research pass against our
own problem claim before writing this section: one pass tried specifically to
disprove it, one tried to find the strongest honest support. Here is what
survived.

**Teach-back is a real, proven, endorsed technique — for the live version.**
A meta-analysis of teach-back in heart failure discharge education found it
reduced readmission with an odds ratio of 0.40–0.55 across six pooled studies
([*Patient Education and Counseling*, 2022, PMID 36411152](https://pubmed.ncbi.nlm.nih.gov/36411152/)).
Project RED, a randomised controlled trial of a nurse-led discharge process
built around teach-back-style confirmation, cut combined 30-day readmissions
and ED visits by roughly 30% against usual care
([Jack et al., *Annals of Internal Medicine*, 2009](https://www.acpjournals.org/doi/10.7326/0003-4819-150-3-200902030-00007)).
Teach-back is formally endorsed by AHRQ, the Joint Commission, the National
Quality Forum, and covered in the NHS's own Health Literacy Toolkit (2nd ed.,
2023). Our tool's mechanism — a simulated reader gives a teach-back response,
a judge checks it — is a direct automation of that specific, evidenced
technique, not an invented one.

**What the evidence does *not* support, and we are not claiming: that a
confusing written document, on its own, causes readmission.** A 19-RCT
meta-analysis found communication interventions do reduce readmission
(RR 0.69) — but the effect came entirely from *active* processes (medication
counselling, disease-management education); pure communication-technique
interventions with no active human process showed no effect at all (RR 1.06,
not significant) ([Becker et al., *JAMA Network Open*, 2021](https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2781605)).
More directly: two independent studies that tested our exact mechanism —
scoring a discharge letter's quality or clarity against 30-day readmission —
both found **no significant relationship**, one in mental health (BJPsych
Open, 2025, DOI 10.1192/bjo.2025.56) and one in COPD/CHF geriatric patients
([*BMC Geriatrics*, 2024, PMC11238400](https://pmc.ncbi.nlm.nih.gov/articles/PMC11238400/)) —
and neither study measured whether the patient actually read or understood
the letter, only the letter's own quality score. A systematic review of 37
studies on the causes of preventable readmission doesn't list patient
comprehension or health literacy as a factor at all; the dominant drivers are
comorbidity burden, age, prior utilisation and severity
([Vest et al., *Implementation Science*, 2010, PMC2996340](https://pmc.ncbi.nlm.nih.gov/articles/PMC2996340/)).

**So here is the honest claim we're actually making:** teach-back works, and
is proven to work, when a clinician has time to do it live with a patient.
Real discharge is time-pressured, and the evidence above shows the technique
*without* that active human time doesn't move outcomes — which is exactly the
gap between "endorsed best practice" and "what scarce staff time can actually
deliver to every patient, every time." Our tool doesn't claim to reduce
readmission, and we won't say it does. It scales the *screening* step of a
proven technique — catching the written phrasing most likely to defeat a
teach-back before a document reaches a patient — at a point where no
systematic check currently exists at all. Whether that screening step itself
moves any downstream clinical outcome is untested, and we say so plainly
rather than imply otherwise.

NICE guideline NG27 ("Transition between inpatient hospital settings and
community or care home settings") sets out what must be communicated to a
patient at discharge — the direct equivalent, for discharge content, of the
mandatory patient user-testing that medicine leaflets (PILs) already require
under EU/UK law before approval. That existing requirement is exactly why we
are *not* pitching PIL-authoring teams as the buyer here: PILs already have a
forcing function and a mandated check. AI-drafted discharge and take-home
instructions do not, yet. Separately, a March 2023 survey of over 3,000
patients and clinicians (Kent Surrey Sussex AHSN with the UK National
Innovation Centre for Ageing, VOICE, and Pfizer UK) found only 32% of patients
said they completely understood the medicine leaflet in their own medicine box
— supporting evidence that written patient instructions are already a
comprehension problem, independent of any readmission claim. Source:
[Only a third of patients fully understand Patient Information Leaflets — The Pharmacist](https://www.thepharmacist.co.uk/news/only-a-third-of-patients-fully-understand-patient-information-leaflet/)
(accessed 2026-10-17). For context on scale, not as a causal claim: 14.8% of
all emergency hospital admissions in England in 2023/24 were readmissions
within 30 days of a previous discharge, rising to 17.9% for patients 75+
([NHS England Digital, published 27 Nov 2025](https://digital.nhs.uk/data-and-information/publications/statistical/compendium-emergency-readmissions/current)).

Our test set is built from real NHS patient-facing medicine and treatment pages
and one real MHRA leaflet (see "Data" below) — patient take-home instructions of
the same kind an AI discharge-drafting tool produces, not literal hospital
discharge letters we don't have access to. We say so plainly rather than
overclaiming the fit.

**This is a misunderstanding-risk check, not a factual-groundedness check.** A
RAGAs-style groundedness checker asks "is this paraphrase supported by the source
text?" We ask a different question: "does a lay reader's teach-back reveal they are
likely to act on a misreading of this instruction, even though every word in the
source is itself accurate?" A sentence can be 100% grounded in the source and still
be dangerously misread — a reversed-sounding instruction, a dropped dose limit, a
double negative. That is the opposite failure mode, and it is the one this tool is
built to catch.

## Why this beats a plain readability checker

*(one sentence, rehearsed)* A readability score only measures how hard a sentence is
to decode, not whether the reader decoded its *meaning* correctly — on our test set
every document scored "too hard" by Flesch-Kincaid/SMOG regardless of whether it
contained a dangerous reversed instruction, because reversing an instruction's
meaning barely changes its syllable count or sentence length.

## The pipeline

1. **Input** — a real patient-facing document (MHRA Patient Information Leaflet or
   NHS condition/treatment page), or a clearly-labelled synthetic variant of one.
2. **Paraphrase step** ([src/paraphrase.py](src/paraphrase.py)) — an LLM role-played
   as a layperson with no medical background gives a **teach-back answer**: what
   they understood they're meant to do, the way a nurse's bedside teach-back check
   asks a real patient to say it back in their own words. This is a **simulated
   reader**, not a real patient — labelled as such everywhere it appears.
3. **Judge step** ([src/judge.py](src/judge.py)) — a second LLM call compares the
   paraphrase against the source and flags a likely misunderstanding with: the
   specific risk type (reversed instruction, dropped condition, ambiguous negation,
   dangerous confidence), a severity score (1–5) and confidence (0–1), and the exact
   source phrase responsible.
   **Reader panel** ([src/panel.py](src/panel.py)) — optionally, the same
   teach-back is run by five simulated readers defined by reading behaviour only
   (skimmer, limited health literacy, English as an additional language, older adult
   on several medicines, anxious reader). The panel flags a document if any reader
   misreads it. This rule was fixed before it was evaluated.
4. **Review queue** (web UI, `/queue`) — every flagged check waits as *pending* for a
   named reviewer, who can **confirm** the risk, **dismiss** it (a reason is
   required), or **edit the source and retest** their own rewrite. Every decision is
   logged with name, time and reason in `outputs/review.db`. Nothing is auto-approved
   or auto-rejected. See "Who reviews flagged cases" below.
5. **Baseline comparator** ([src/baseline_readability.py](src/baseline_readability.py))
   — the same documents run through a plain Flesch-Kincaid/SMOG readability
   threshold flag, required by the track brief as the "AI at the core" comparison.

## Results on our labelled test set

Run `python -m src.pipeline --all` then `python -m src.eval` to reproduce. Primary
labelled test set: n=8 documents (4 real, unmodified; 4 real documents with one
sentence deliberately rewritten to be technically accurate but genuinely confusing).
**Measured result: our method 4/4 catch rate, 0/4 false positives; the readability
baseline 4/4 catch rate, 4/4 false positives** — it flags every document in the set
identically, real or planted, because reversing an instruction's meaning barely
changes its syllable count. Full per-document numbers, four additional hand-built
edge cases probing harder failure patterns, and the one documented failure case:
[EVAL_RESULTS.md](EVAL_RESULTS.md).

**This is a hackathon-weekend test set (n=8 primary + 4 edge cases), not a
population-level validation.** See "Honest limits" below.

> **Caveat found after the locked run:** the locked pipeline sent each file's header
> to the models, and on synthetic files that header contains the answer key. A
> header-stripped rerun over all 12 documents (`python -m src.panel_eval`) gave:
> **single reader 4/7 caught, 1/5 false alarms; reader panel 6/7 caught, 2/5 false
> alarms, at ~5× the model cost and +2s.** The panel catches the documented failure
> case; the trade-off is one extra false alarm. Full detail:
> [EVAL_RESULTS.md § Reader panel vs single reader](EVAL_RESULTS.md#reader-panel-vs-single-reader-n12-header-stripped).

## What this looks like downstream, for the patient

The pipeline itself never shows anything to a patient — it flags a risk for the
reviewer described below, who decides what's safe to share. Two things make that
downstream step concrete, both **illustrative, not a live product**:

- [pitch/patient_safety_walkthrough.html](pitch/patient_safety_walkthrough.html) —
  a static, standalone pitch asset built on this project's own evaluated
  `synthetic_paracetamol_duration_reversed` test case, showing the reviewed leaflet
  a pharmacist would eventually share with a patient and the same draft's outcome
  with and without the checker, side by side. Open it directly in a browser, no
  server required — it was added after the core pipeline and evaluation were
  already locked, and changing it carries none of the risk that changing the
  pipeline or test set would.
- **In the web app**, every run's result page links to `/run/<id>/patient-view` —
  the same idea, but live and specific to whichever document was actually
  reviewed: it shows what readers flagged, what a reviewer decided, and the
  resulting text, built entirely from that run's own stored data (no new model
  call). Where the static mockup is a fixed pitch-deck slide, this is the general
  version that works for any document run through the tool, dismissed or edited.

## Who reviews flagged cases, and who can override

Every flag from the judge step goes into a review queue, not an automatic block.
For a real deployment, the qualified reviewer named by this workflow would be a
**discharge-documentation lead, health-literacy reviewer, or clinician on the team
responsible for the patient-facing content** (e.g. the discharge-documentation
lead or patient-safety lead who already signs off discharge/take-home
instructions) — not "a human" in the abstract. They can accept the flag, dismiss
it as a false alarm, or edit the source sentence directly; nothing is removed or
published without that sign-off. This tool produces evidence for that reviewer,
it does not replace their judgement — see the track rule on "show qualified human
review and link to official guidance" below.

Relevant official guidance this review step is meant to sit alongside:
[NICE guideline NG27 — Transition between inpatient hospital settings and
community or care home settings](https://www.nice.org.uk/guidance/ng27), which
sets out what must be communicated to a patient at discharge, and
[NHS England's Health Literacy / Accessible Information guidance](https://www.england.nhs.uk/ourwork/accessibleinfo/).

## Data — real, public, no patient data involved

| doc_id | Type | Source | Accessed |
|---|---|---|---|
| `pil_amoxicillin` | MHRA Patient Information Leaflet | [Amoxicillin 250mg Capsules PIL, Aurobindo Pharma – Milpharm Ltd, electronic Medicines Compendium](https://www.medicines.org.uk/emc/product/541/pil) | 2026-10-17 |
| `nhs_antibiotics` | NHS condition page | [NHS — Antibiotics](https://www.nhs.uk/conditions/antibiotics/) | 2026-10-17 |
| `nhs_paracetamol` | NHS medicines page | [NHS — Paracetamol for adults: how and when to take](https://www.nhs.uk/medicines/paracetamol-for-adults/how-and-when-to-take-paracetamol-for-adults/) | 2026-10-17 |
| `nhs_ibuprofen` | NHS medicines page | [NHS — Ibuprofen for adults](https://www.nhs.uk/medicines/ibuprofen-for-adults/) | 2026-10-17 |

Full text and licence notes for each are in [data/sources/](data/sources/) (one
`.txt` file per document, each with a header recording product/page name, source
URL, access date, and reuse terms). NHS website content is published under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Patient Information Leaflet text is MHRA-regulated content published for patient use
on the electronic Medicines Compendium (operated by Datapharm); reproduced here for
non-commercial, educational hackathon research/demo purposes with source, product
and date recorded, not for further redistribution.

### Deliberately ambiguous synthetic test cases — clearly labelled, every time

Four of the eight test documents are **synthetic/modified**: the SotonShip 2026 team
took one real sentence from the above sources and rewrote it to be technically
defensible but genuinely confusing (a reversed-sounding minimum/maximum duration, or
a double negative that can be misread as endorsing a double dose), leaving
everything else as the real, unmodified text. Every such file lives under
[data/sources/synthetic/](data/sources/synthetic/), is named with a `synthetic_`
prefix, carries a `*** SYNTHETIC / MODIFIED TEST CASE ***` header stating exactly
what was changed and why, and is marked `is_synthetic = TRUE` in
[data/documents.csv](data/documents.csv) — the single source of ground truth labels
used for the evaluation numbers above. The CLI output and demo narration also state
"SYNTHETIC / MODIFIED TEST CASE" for these documents every time they are run, not
just once. No real patient data, real patient conversation, or anything other than
public-source text / our own labelled synthetic modification of it appears anywhere
in this repository.

| doc_id | Base source | What was changed | Planted risk type |
|---|---|---|---|
| `synthetic_paracetamol_duration_reversed` | NHS paracetamol page | "do not take for more than 3 days" → reworded as a confusing double-negative that reads as a 3-day *minimum* | reversed_instruction |
| `synthetic_ibuprofen_duration_reversed` | NHS ibuprofen page | "do not take for more than 10 days" → reworded to read as a 10-day *minimum* | reversed_instruction |
| `synthetic_amoxicillin_misseddose` | Amoxicillin PIL | missed-dose guidance reworded with a double negative ("don't not take it") plus a reversed double-dose instruction | double_negative_and_reversed_instruction |
| `synthetic_antibiotics_doubledose` | NHS antibiotics page | "do not take a double dose" → reworded as an ambiguous negation that reads as endorsing a double dose | double_negative_and_reversed_instruction |

Four more hand-built edge cases (including one deliberate failure) were added
*after* this primary set to stress-test harder patterns — see
[EVAL_RESULTS.md](EVAL_RESULTS.md) for all four, reported in full rather than folded
into the headline numbers above.

## Cost estimate

**Measured cost of this demo: $0.2096 for all 8 primary documents (~$0.026/document),
printed live by `python -m src.pipeline --all`.** That number reflects the transport
we actually used (see "A note on how the LLM calls are authenticated" below), which
carries agent-harness overhead a production integration wouldn't have. The number
that matters for the business case — a direct Anthropic API call with no harness —
works out to roughly **$0.007–0.01/document** on this project's document lengths and
current Anthropic API pricing (checked 2026-10-17: Claude Haiku 4.5 $1.00/$5.00 per
million input/output tokens for the paraphrase step; Claude Sonnet 5 $2.00/$10.00 per
million input/output tokens for the judge step). See
[EVAL_RESULTS.md § Cost estimate](EVAL_RESULTS.md#cost-estimate) for both numbers in
full, the comparison against an estimated human-reviewer time cost, and the proposed
pricing model.

## Honest limits

This tool has been validated on **8 documents we selected and labelled ourselves
over one hackathon weekend.** Before this could be trusted on a real patient, it
would need: review and sign-off from a qualified health-literacy specialist or
clinician (not just the hackathon team) on both the risk taxonomy and the judge
prompt; testing against real readers' teach-back answers, not just a simulated
layperson LLM call, to confirm the simulated paraphrase actually predicts real
misunderstanding; and a much larger, more diverse labelled test set spanning more
drug classes, more NHS page types, and a wider range of planted-risk categories than
the four we hand-authored. See [EVAL_RESULTS.md](EVAL_RESULTS.md) for the one
documented failure case and what it implies.

No claim here goes beyond what our own test numbers support. We do not claim this
tool is "safe" or "compliant" — only that, on this 8-document labelled test set, it
achieved the measured catch-rate and false-positive-rate reported in
[EVAL_RESULTS.md](EVAL_RESULTS.md). The problem framing itself has an evidenced
limit too, set out in full near the top of this README under "What the evidence
actually supports": the live teach-back technique our tool automates has real,
meta-analytic evidence behind it (OR 0.40–0.55 for readmission, an RCT showing
~30% reduction), but we found no evidence — and two independent null studies
directly against it — that a confusing *written* document on its own causes
readmission. We do not claim this tool reduces readmission. We claim it scales
a proven technique's screening step to a point in the process where no
systematic check exists today, and we say plainly that whether that screening
step itself changes any downstream clinical outcome is untested.

## AI-disclosure statement

**What existed before the event:** only `briefs/responsible-ai-brief.pdf` and
`briefs/southampton-city-brief.pdf` (the SotonShip 2026 organisers' own track briefs,
supplied to all teams) and `BUILD_PROMPT.md` (the team's own written project brief,
drafted before hacking opened to scope the idea, not generated by an AI model). No
other code, prompts, or project content predate this repository's creation after
hacking opened. Everything described below was built during the event.

This entire repository — the pipeline code, the prompts, the synthetic test-case
rewrites, the evaluation scripts, and this README — was built from scratch during
SotonShip 2026 (hacking opened Friday 16 Oct 20:00 BST), using Claude Code
(Anthropic) as a pair-programming/build assistant. No code from any earlier project
was imported. The paraphrase and judge pipeline steps themselves call Claude models
(Claude Haiku 4.5 and Claude Sonnet 5, via the Claude Code CLI under the team's own
Claude subscription — see "A note on how the LLM calls are authenticated" above) at
runtime — that AI generation is the product's core function, not incidental tooling,
and every output it produces is labelled as a flag for human review, never as a final
determination. The real source documents (PIL and NHS page text) are reproduced
verbatim from their original publishers, not AI-generated; the synthetic test-case
rewrites were hand-drafted by the team (with Claude Code assistance) specifically to
plant a known, labelled misunderstanding risk for evaluation purposes.

## Credits, licences and dates

| Component | Licence | Notes |
|---|---|---|
| [Claude Code CLI](https://www.npmjs.com/package/@anthropic-ai/claude-code) (`@anthropic-ai/claude-code`) | Anthropic commercial product | Non-interactive transport for the paraphrase + judge LLM calls, authenticated via Claude subscription — see "A note on how the LLM calls are authenticated" above |
| [Prometheux](https://prometheux.ai) ontology-reasoning engine | Commercial product | **Not integrated** — referenced only via the roadmap specification [prometheux/comprehension_gap_ontology_prompt.md](prometheux/comprehension_gap_ontology_prompt.md); no code in this repository calls it |
| [textstat](https://pypi.org/project/textstat/) | MIT | Flesch-Kincaid / SMOG baseline comparator |
| [NLTK](https://pypi.org/project/nltk/) | Apache-2.0 | Syllable-counting backend for textstat |
| [CMU Pronouncing Dictionary](https://github.com/Alexir/CMUdict) (cmudict 0.7a) | Carnegie Mellon University, freely redistributable (same terms NLTK itself redistributes it under) | Bundled in [nltk_data/](nltk_data/) so the baseline works offline on a fresh clone, rather than depending on an NLTK auto-download that failed with an SSL error mid-build |
| Claude Haiku 4.5 / Claude Sonnet 5 | Anthropic | Paraphrase + judge model calls; usage and per-call pricing checked 2026-10-17 |
| Amoxicillin 250mg Capsules PIL | MHRA-regulated / electronic Medicines Compendium | See [data/sources/pil_amoxicillin_250mg_capsules.txt](data/sources/pil_amoxicillin_250mg_capsules.txt) |
| NHS condition/medicines pages | Open Government Licence v3.0 | See [data/sources/](data/sources/) headers |
| "Only a third of patients fully understand PILs" (The Pharmacist, reporting a KSS AHSN / NICA / VOICE / Pfizer UK survey) | Cited for its finding, not reproduced | Problem-evidence citation only; accessed 2026-10-17 |
| [AI-assisted discharge summary pilot, Chelsea and Westminster NHS Foundation Trust (Digital Health News)](https://www.digitalhealth.net/2025/08/ai-assisted-tool-on-fdp-will-help-write-hospital-discharge-letters/) | Cited for its finding, not reproduced | Evidence that AI drafting of discharge content is real and current, not hypothetical; accessed 2026-10-17 |
| [NICE guideline NG27 — Transition between inpatient hospital settings and community or care home settings](https://www.nice.org.uk/guidance/ng27) | UK Open Government Licence (NICE content) | Official guidance our human-review step sits alongside, per the track rule on qualified review for health uses; accessed 2026-10-17 |
| [NHS England Digital — Compendium: Emergency readmissions to hospital within 30 days of discharge](https://digital.nhs.uk/data-and-information/publications/statistical/compendium-emergency-readmissions/current) | Cited for its finding, not reproduced | Problem-evidence citation (14.8% / 17.9% readmission rates); published 27 Nov 2025, data to 31 Mar 2025; accessed 2026-10-17 |
| [Quality of discharge letters concerning readmissions to mental healthcare: case-control study](https://doi.org/10.1192/bjo.2025.56) (BJPsych Open) | Cited for its finding, not reproduced | Honest counter-evidence — found no significant discharge-letter-quality-to-readmission link (mental health, UK); accessed 2026-10-17 |
| [Discharge letter quality and 30/90-day readmission](https://pmc.ncbi.nlm.nih.gov/articles/PMC11238400/) (BMC Geriatrics, 2024, PMC11238400) | Cited for its finding, not reproduced | Honest counter-evidence — a second, independent null result on letter quality vs. readmission (COPD/CHF geriatric patients); accessed 2026-10-17 |
| [Determinants of preventable readmissions in the United States: a systematic review](https://pmc.ncbi.nlm.nih.gov/articles/PMC2996340/) (Vest et al., Implementation Science, 2010, PMC2996340) | Cited for its finding, not reproduced | Honest counter-evidence — 37-study review of readmission causes; patient comprehension/health literacy not identified as a cause; accessed 2026-10-17 |
| [Interventions to Improve Communication at Hospital Discharge and Rates of Readmission](https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2781605) (Becker et al., JAMA Network Open, 2021) | Cited for its finding, not reproduced | 19-RCT meta-analysis — communication interventions reduce readmission only via active processes (counselling/education); pure technique alone showed no effect; accessed 2026-10-17 |
| [Teach-back and readmission in heart failure: meta-analysis](https://pubmed.ncbi.nlm.nih.gov/36411152/) (Patient Education and Counseling, 2022, PMID 36411152) | Cited for its finding, not reproduced | Evidence for the live teach-back technique specifically (OR 0.40–0.55 for readmission, 6 pooled studies); accessed 2026-10-17 |
| [Project RED: A Reengineered Hospital Discharge Program](https://www.acpjournals.org/doi/10.7326/0003-4819-150-3-200902030-00007) (Jack et al., Annals of Internal Medicine, 2009) | Cited for its finding, not reproduced | RCT — nurse-led discharge process with teach-back-style confirmation cut 30-day readmission/ED visits ~30% vs. usual care; accessed 2026-10-17 |

## A note on how the LLM calls are authenticated

The track's suggested stack calls for `ANTHROPIC_API_KEY` from the environment (a
separately-billed Anthropic API key). We started there, but the team's API key had no
credit balance and we did not want to pay for a separate top-up mid-hackathon, so
[src/claude_cli.py](src/claude_cli.py) instead shells out to the **Claude Code CLI**
in non-interactive print mode (`npx @anthropic-ai/claude-code -p ...`, `--tools ""`
to disable all agentic tools, used purely as a one-shot prompt/response transport),
authenticated against the team's own Claude subscription rather than a metered API
key. This is a disclosed, deliberate swap made for hackathon budget reasons, not the
architecture we'd recommend for production — see the cost estimate above for why: a
direct API integration has no agent-harness overhead and would be both simpler and
cheaper per call. Either transport calls the same underlying Claude models with the
same prompts; only the auth/billing path differs.

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npx -y @anthropic-ai/claude-code    # one-time: run interactively and /login with a Claude subscription
.venv/bin/python -m src.pipeline --doc data/sources/pil_amoxicillin_250mg_capsules.txt   # one document, live
.venv/bin/python -m src.pipeline --all                                                    # all 8 documents -> outputs/results.csv
.venv/bin/python -m src.eval                                                              # catch-rate / false-positive-rate table -> outputs/eval_summary.csv
```

No credentials of any kind are committed anywhere in this repository.

### Web UI

A Flask app ([webapp/](webapp/)) runs the full reviewer workflow in a browser:

1. **Run a check**: pick a document and choose *1 reader* or *Reader panel*. A
   progress screen shows each simulated reader turn green (understood) or red
   (misread) as it finishes.
2. **Result**: the headline ("3 of 5 simulated readers misread this"), the source
   document with the misread sentence highlighted (hover to see which readers), each
   reader's teach-back and judge output, and the readability baseline. If the judge's
   quoted phrase isn't in the source word for word, the page says so instead of
   highlighting a guess.
3. **Review queue** (`/queue`): flagged runs wait for a named reviewer to confirm,
   dismiss with a reason, or **edit and retest**. The reviewer rewrites the wording
   themselves (the tool does not generate fixes), and the retest shows the
   before/after score side by side. Decisions are logged in `outputs/review.db`.
4. **Evaluation** (`/eval`): the locked results and the header-stripped panel
   comparison.

It calls the same `src/` functions as the CLI. Only the document body is sent to a
model; the file header (provenance and, for synthetic cases, the answer key) is
stripped by [src/documents.py](src/documents.py).

```bash
.venv/bin/python -m webapp.app    # http://localhost:5050
```

The CLI remains the pipeline's primary, scriptable interface (what `--all` and `eval`
use to produce the locked numbers). The panel has its own entry points:

```bash
.venv/bin/python -m src.panel --doc data/sources/synthetic/synthetic_paracetamol_duration_reversed.txt
.venv/bin/python -m src.panel_eval   # single reader vs panel on all 12, header stripped
```

## Business case

**User:** the discharge-documentation lead, medicines-information pharmacist, or
patient-safety lead at an NHS trust who is already reviewing AI-drafted patient
take-home instructions and is accountable for them reaching patients correctly.
**Buyer:** an NHS AI-vendor building discharge-documentation drafting tools (the
kind piloted at Chelsea and Westminster NHS Foundation Trust under the
government's AI Exemplars programme) who needs an assurance layer their tool can
point to before a trust's clinical-governance process will sign off on it — not
the trust buying a point tool one document at a time. Selling through the vendor
reaches every trust that vendor's tool is deployed in, rather than one
trust-by-trust sale with NHS procurement timelines. **Why us over an existing
tool:** existing AI-content checkers (RAGAs-style groundedness tools, generic
readability plugins) check a different, narrower thing — whether the text is
accurate or syllable-simple — not whether a lay reader will act on a misreading
of an instruction that is itself accurate; we found no deployed product doing
comprehension-gap checking the way this does — the closest prior work is an
academic benchmark (DischargeBench), not a product with a human-review workflow.
**Second customer:** every further NHS trust the same vendor's drafting tool
reaches, with no retuning beyond swapping in that trust's own document set — the
risk taxonomy and review-queue workflow are domain-general to any patient-facing
instruction text, not tuned to one trust's house style. A second AI-vendor in the
same space (not just Chelsea and Westminster's) is the second step beyond that.

**Roadmap — explainable data lineage:** [prometheux/comprehension_gap_ontology_prompt.md](prometheux/comprehension_gap_ontology_prompt.md)
is a ready-to-run ontology specification, written against this project's exact
data model, for running the full chain — document → simulated reader → judge →
risk-type → reviewer decision — through [Prometheux](https://prometheux.ai)'s
ontology-reasoning engine, so a governance reviewer or auditor can query *why*
something was flagged and trace it deterministically, independent of reading the
application code. **Not integrated or run tonight** — it is a specification, not
a tested feature, and is labelled as such in the file itself. We're naming it here
as evidence of what "a second customer's due-diligence team would ask for next"
actually looks like in concrete terms, not as a claim that it works.
