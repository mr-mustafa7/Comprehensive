# Prometheux ontology prompt — comprehension-gap checker data lineage

Status: **not integrated tonight — this is a ready-to-run specification**, written
against this project's real data model so it can be fed into Prometheux directly
rather than adapted from a guess. Positioned as a roadmap / "what's next" artifact
for the Responsibility-and-trust and Business/scale story, not a live demo.

## Why this, and why Prometheux specifically

Every number this project reports — a catch rate, a false-positive rate, a
confidence score — is currently explainable only by reading the code or the raw
`outputs/*.csv` / `webapp/store.py` SQLite rows by hand. That's honest but not
*legible*: a governance reviewer, a procurement team doing due diligence, or an
auditor asking "why was this specific document flagged, and what happened to it
after" has to go spelunking. An ontology-native reasoning layer over the same data
— entities and relationships defined once, queried deterministically, with every
answer traceable back to the rows that produced it — is exactly the kind of visible
data lineage a Responsible AI buyer should expect to see before trusting a
governance tool, and it's a different, complementary kind of "explainable AI" to
the LLM-based judge itself: deterministic and auditable where the judge is
probabilistic and language-based. Running the panel's output *through* an ontology
engine, rather than just logging it, is the point — it turns "trust us, here's a
CSV" into "query it yourself, here's why."

## The real data this ontology is built on

Source: `webapp/store.py` (SQLite, `outputs/review.db`) and `data/documents.csv`.
Field names below are exact, not paraphrased — copy them as-is into the ontology
definition.

### `Document` (from `data/documents.csv`)
- `doc_id` (string, primary key)
- `title` (string)
- `doc_type` (string: `medication_leaflet` | `nhs_condition_page` | `nhs_medicine_page`)
- `source_url` (string)
- `access_date` (date)
- `is_synthetic` (boolean — **must be carried through every downstream entity's
  lineage query**; a synthetic/modified test case must never be indistinguishable
  from a real document at any point in the ontology, per this project's own
  labelling rule)
- `test_set` (string: `primary` | `edge_case`)

### `Run` (from `runs` table — one per check performed)
- `id` (integer, primary key)
- `created_at` (timestamp)
- `doc_id` (string — joins to `Document.doc_id`, but note: `title`,
  `is_synthetic`, `source_url` and `access_date` are **denormalized onto the run
  itself at write time**, not purely joined — a retest run's `doc_id` is the
  original document's id, but its `title` is prefixed `"Edited: ..."`. Model
  both: a `CHECKED_IN` edge to `Document` for provenance, and the run's own
  denormalized fields as the ones actually shown to a reviewer, since they can
  diverge (e.g. an edited run's title) and the divergence itself is meaningful.
- `mode` (string: `single` | `panel`)
- `parent_run_id` (foreign key → `Run.id`, nullable — set when this run is a
  reviewer's retest of an edited document)
- `document_text` (text — the exact text shown to the readers for this run; for a
  retest this differs from the parent's `document_text`, which *is* the point)
- `result_json` (JSON blob — contains the nested `readers` array; see
  `ReaderResponse` and `Judgment` below, both derived from parsing this field)
- `flagged` (boolean — true if any reader's judge call flagged)
- `status` (string: `pending` | `confirmed` | `dismissed` | `edited` | `not_flagged`)
- `elapsed_s` (float — wall-clock seconds for the run)
- `cost_usd` (float)

### `ReaderResponse` (nested inside `Run.result_json["readers"]`, one per simulated reader)
- `persona_id` (string — see Persona below)
- `paraphrase` (text — the simulated reader's teach-back answer)
- belongs to exactly one `Run`

### `Persona` (fixed set, from `src/panel.py:PERSONAS` — model as a static ontology class, not a data-derived one)
Five instances, each with `id`, `name`, `description`:
`skimmer`, `limited_literacy`, `second_language`, `older_polypharmacy`, `anxious`.
For single-reader runs, use the fixed persona `id="default"`, `name="Single
simulated reader"`.

### `Judgment` (nested inside each `ReaderResponse.judge`, produced by `src/judge.py`)
- `flagged` (boolean)
- `risk_type` (string — **closed taxonomy, exactly these five values**:
  `reversed_instruction` | `dropped_condition` | `ambiguous_negation` |
  `dangerous_confidence` | `none`)
- `severity` (integer, 1–5)
- `confidence` (float, 0.0–1.0)
- `source_phrase` (text — the exact source sentence the judge blamed; this is the
  single most important lineage edge: it is a literal substring of the `Document`
  the `Run` was performed on, and the ontology should be able to re-locate it there)
- `explanation` (text)
- belongs to exactly one `ReaderResponse`

### `BaselineScore` (nested inside `Run.result_json["baseline"]`, from `src/baseline_readability.py`)
- `flesch_kincaid_grade` (float)
- `smog_index` (float)
- `flagged` (boolean — true if either score exceeds the fixed threshold of 9.0)
- belongs to exactly one `Run` (1:1 — every run gets exactly one baseline score,
  regardless of `mode`, since the baseline runs on the document text once, not
  per-reader)

Include this in the ontology even though it's the *rejected* method — the whole
point of the project's comparison is that `BaselineScore.flagged` is true for
every single document in the evaluation set regardless of `RiskType`, which is
precisely the kind of pattern an ontology/reasoning layer should be able to
surface on its own (e.g. "query: is `BaselineScore.flagged` correlated with
anything other than `Document` length" — the honest answer the project already
found by hand is "no, it's true 8/8 times, see `EVAL_RESULTS.md`" — reproducing
that finding via the ontology rather than a hand-written script would itself be
a demonstration of the engine's value).

### `ReviewDecision` (from `decisions` table)
- `id` (integer, primary key)
- `run_id` (foreign key → `Run.id`)
- `created_at` (timestamp)
- `reviewer` (string — free-text name + role, e.g. "A. Patel, medicines-information pharmacist")
- `action` (string: `confirm` | `dismiss` | `edit`)
- `reason` (text, nullable — required by the application when `action = dismiss`)
- `child_run_id` (foreign key → `Run.id`, nullable — for `action = edit`, the
  retest run created from the reviewer's rewritten text)

## Relationships (the ontology's edges)

```
Document        --[CHECKED_IN]-->     Run            (1 document : many runs)
Run             --[RETESTS]-->        Run             (self-referential, via parent_run_id)
Run             --[PRODUCED]-->       ReaderResponse  (1 run : up to 5 responses)
ReaderResponse  --[READ_AS]-->        Persona         (many : 1)
ReaderResponse  --[JUDGED_AS]-->      Judgment        (1 : 1)
Judgment        --[CLASSIFIED]-->     RiskType        (many : 1, closed taxonomy)
Judgment        --[BLAMES]-->         SourcePhrase     (a located substring of Document.document_text — see note below)
Run             --[SCORED_BY]-->      BaselineScore   (1 : 1)
Run             --[DECIDED_BY]-->     ReviewDecision  (1 run : many decisions, chronological)
ReviewDecision  --[REVIEWED_BY]-->    Reviewer         (many : 1, by name)
```

**Note on `SourcePhrase`:** this is not a stored row — it's a derived entity. The
`source_phrase` string in a `Judgment` should be resolved as a located span inside
the `Run.document_text` it came from (this project's own `webapp/highlight.py`
already does this matching heuristically, tolerating quote-mark and whitespace
differences — reuse that matching logic, or re-implement it, rather than requiring
an exact substring match, since judge output is LLM-generated and not guaranteed
byte-identical to the source).

## What the ontology should make queryable (the actual deliverable)

These are the specific, concrete questions a governance reviewer should be able to
ask and get a deterministic, traceable answer to — this is the test of whether the
ontology is doing real work, not just re-presenting the SQLite tables as a graph:

1. **Full lineage of one flag**: given a `Judgment` (or just a `source_phrase`
   string), trace back to the exact `Document`, the `ReaderResponse` and `Persona`
   that produced it, and forward to every `ReviewDecision` made about the `Run` it
   belongs to — a single query, not a manual join.
2. **Risk-type provenance across the whole dataset**: for each `RiskType`, list
   every `Document` where it was found, split by `is_synthetic` — this should make
   it structurally impossible to accidentally report a synthetic-document finding
   as if it came from a real one, which is a track requirement this project already
   takes seriously (see `data/sources/synthetic/` headers).
3. **Before/after a reviewer's edit**: given a `Run` with `status = edited`, find
   its child `Run` (via `RETESTS`) and diff their `flagged` / `Judgment` sets —
   this is exactly what `webapp/templates/result.html`'s "before/after" card shows
   today, computed by hand in Jinja; the ontology should be able to answer it as a
   query.
4. **Reviewer accountability**: for a given `reviewer` name, list every
   `ReviewDecision` they made, with the `Run` and `Document` each belongs to, and
   whether a `dismiss` decision's stated `reason` is non-empty (the application
   already enforces this at write time; the ontology should be able to verify it
   at read time, independently).
5. **Coverage gap**: documents with `Run`s that are still `status = pending` —
   i.e. flagged, with no reviewer decision yet — surfaced as an explicit query
   result, not just a filtered table (this already exists as the "Pending review"
   section of `webapp/templates/queue.html`; the value of the ontology version is
   that it's the same answer derived independently, from the relationships, not
   from application code that could have a bug).
6. **Baseline discrimination check**: does `BaselineScore.flagged` vary at all
   with `RiskType` or `Judgment.flagged`, across every `Run`? The honest answer
   this project already found by hand (`EVAL_RESULTS.md`) is no — the baseline
   flags every single primary-set document regardless of whether a risk was
   planted. Reproducing that finding as an ontology query, independently of the
   hand-written `src/eval.py` script that originally found it, is itself a
   demonstration of the engine earning its place rather than duplicating work.

## What "visible" should mean for the demo/pitch artifact

A rendered graph view (nodes: Document, Run, Persona, Judgment, RiskType,
ReviewDecision; edges as defined above) for one real traced example — the project's
own `synthetic_paracetamol_duration_reversed` case is the natural one to use, since
it's already the hero example in `DEMO_SCRIPT.md` and has a full
flag → review → edit → retest chain in the data. Style it to match the existing
product's visual language (`webapp/static/style.css` token system: `--accent`
`#0b5c78` for the primary relationship edges, `--danger` for flagged nodes,
`--success` for cleared ones) rather than Prometheux's own default theme, so it
reads as part of the same product rather than a bolted-on screenshot.

## Honest scope note

This is a specification, not a tested integration — it has not been run against
Prometheux, and no claim is made that it works as written on the first attempt.
Treat it the same way the rest of this project treats untested claims: as a
concrete, falsifiable next step, not a feature.
