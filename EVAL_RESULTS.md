# Evaluation results

Reproduce with:

```bash
.venv/bin/python -m src.pipeline --all   # writes outputs/results.csv
.venv/bin/python -m src.eval             # writes outputs/eval_summary.csv, prints the table below
```

> **Read this first: answer-key leak found after the locked run.** `src/pipeline.py`
> sends each source file to the models *including its header*. On synthetic files that
> header states the original sentence, the planted sentence, the risk type and the
> ground-truth label; on real files it says the page is real NHS/MHRA text. The locked
> numbers in the next two sections were produced with that header visible to the
> reader and the judge. A fresh, header-stripped rerun is reported in
> [Reader panel vs single reader](#reader-panel-vs-single-reader-n12-header-stripped)
> below, and does **not** reproduce the locked 4/4 caught, 0/4 false positives.

## Primary labelled test set (n=8, pre-registered before any failure-case hunting)

4 real, unmodified documents (no planted misunderstanding) + 4 real documents with one
sentence deliberately rewritten to be technically accurate but genuinely confusing
(clearly labelled `SYNTHETIC / MODIFIED TEST CASE` in [data/sources/synthetic/](data/sources/synthetic/)
and in `data/documents.csv`). This set was run once, in full, before we went looking for
a failure case — the numbers below are exactly what that first run produced, not a
cherry-picked subset.

| Method | Catch rate | False-positive rate |
|---|---|---|
| **Comprehension-gap checker** (this tool) | **4/4 (100%)** | **0/4 (0%)** |
| Readability-score baseline (Flesch-Kincaid/SMOG, threshold = grade 9) | 4/4 (100%) | 4/4 (100%) |

**n=8 is a hackathon-weekend test set, not a population-level validation.** See
"Honest limits" in [README.md](README.md).

The baseline's 100%/100% is not a coincidence or a bad threshold choice — it is the
central finding. Every one of these 8 documents (real and synthetic) scores "too hard
for the general public" on Flesch-Kincaid/SMOG, because they are all real MHRA/NHS
medical text written at a similar reading grade. Reversing an instruction's meaning
barely changes its syllable count or sentence length, so a readability score cannot
tell a dangerous planted reversal apart from a clean document — it flags both, or
neither, identically. That is exactly the gap this tool is built to close.

### Per-document detail (from `outputs/results.csv`)

| doc_id | planted? | ground truth risk | method flagged | method risk_type | method confidence | method source_phrase |
|---|---|---|---|---|---|---|
| `pil_amoxicillin` | no | — | False | none | 0.80 | — |
| `nhs_antibiotics` | no | — | False | none | 0.90 | — |
| `nhs_paracetamol` | no | — | False | none | 0.90 | — |
| `nhs_ibuprofen` | no | — | False | none | 0.85 | — |
| `synthetic_paracetamol_duration_reversed` | yes | reversed_instruction | **True** | reversed_instruction | 0.95 | "Paracetamol shouldn't be stopped before 3 days are up, unless your doctor hasn't said otherwise." |
| `synthetic_ibuprofen_duration_reversed` | yes | reversed_instruction | **True** | reversed_instruction | 0.95 | "ibuprofen tablets and capsules are not to be discontinued ahead of the 10-day mark" |
| `synthetic_amoxicillin_misseddose` | yes | double_negative_and_reversed_instruction | **True** | reversed_instruction | 0.93 | "never skip doubling up if you've missed more than one in a row" |
| `synthetic_antibiotics_doubledose` | yes | double_negative_and_reversed_instruction | **True** | ambiguous_negation | 0.93 | "Missing a dose isn't a reason not to take two next time" |

In every planted case the judge named the *exact* sentence we had rewritten, at high
confidence (0.93–0.95) — not a coincidental flag.

## Extended edge-case stress test (n=4, built *after* the primary run, specifically to find a failure)

A clean 100%/0% on n=8 is a result worth being suspicious of, not proud of — the same
people who wrote the judge prompt wrote the test sentences, so of course the prompt
is tuned to catch the pattern it was built against. Rather than report the primary
set as the whole story, we deliberately built four harder, more varied edge cases
afterward, targeting patterns the primary set didn't cover, and ran each once with no
retries. These are **not** folded into the n=8 headline numbers above — that would be
reporting a secretly-expanded, cherry-picked test set as if it were pre-registered.
They are reported here in full, including the one that failed.

| doc_id | what it tests | ground truth | result |
|---|---|---|---|
| `synthetic_ibuprofen_nsaid_softened` | a flat prohibition reframed as a soft, common practice ("people sometimes combine... check with a pharmacist") — no negation trick, just a dropped prohibition | planted (dropped_condition) | **Caught.** Flagged `dropped_condition`, confidence 0.90, named the exact rewritten sentence, correctly explained the dropped stomach-ulcer/bleeding risk. |
| `synthetic_amoxicillin_kidney_selfadjust` | a clinician-led dose adjustment reworded into patient self-adjustment ("use your judgement on how much less") — a dangerous_confidence pattern, no negation at all | planted (dangerous_confidence) | **Caught.** Flagged `dangerous_confidence`, confidence 0.93, correctly identified that the reader had not picked up the "talk to your doctor" instruction. |
| `synthetic_amoxicillin_driving_stacked_negation` | a real instruction stacked with three negations, but — unlike our other cases — its *meaning is unchanged* under careful parsing (a control, not a planted risk) | clean (control) | **Correctly not flagged.** The paraphrase resolved the stacked negation correctly ("I shouldn't drive... unless I'm sure I feel well enough"), and the judge did not raise a false alarm just because the source sentence was awkwardly worded. |
| `synthetic_amoxicillin_fulltext_buried` | the *same already-proven* missed-dose double-negative risk, but embedded in the full, untrimmed leaflet (including its long, dramatic side-effects list) instead of our shortened version | planted (double_negative_and_reversed_instruction) | **Failed — see below.** |

### The one deliberate failure case

`synthetic_amoxicillin_fulltext_buried` plants the exact same reversed missed-dose
sentence that the primary test set caught at 0.93 confidence (`synthetic_amoxicillin_misseddose`).
The only change: this version keeps the leaflet's full, ~900-word "Possible side
effects" section — allergic reactions, DRESS syndrome, aseptic meningitis, jaundice,
blood disorders — instead of the trimmed list we used in the primary set.

**What happened:** the paraphrase step's teach-back (deliberately constrained to 2–5
sentences, like a real bedside teach-back) was dominated by the dramatic side-effect
content and **never mentioned the missed-dose instruction at all** — not confused
about it, just silent on it:

> "I'm meant to take the capsules with a glass of water, spacing the doses out
> through the day and finishing the whole course even if I feel better. If I get a
> rash, swelling of the face or lips, trouble breathing, or bad diarrhoea, I should
> stop taking them and see a doctor straight away. I also need to watch for
> yellowing skin, dark urine, or unusual bruising, and tell my doctor if any of
> these happen."

The judge, comparing this paraphrase against the source, correctly noticed *a*
problem — that the reader treats "yellowing skin, dark urine, bruising" (serious
liver/blood warning signs, told to the doctor) with less urgency than the rash/
breathing symptoms (told to stop and see a doctor immediately) — and flagged
`dropped_condition` at a low, honest confidence of **0.40**. But it flagged the
**wrong thing**: it never identified the actual planted risk (the reversed
double-dose instruction), because that risk never surfaced in the paraphrase for the
judge to compare against in the first place. By our strict "did it name the actual
planted risk" standard, this is a **miss** — a right-shaped flag (something IS
wrong here) landing on the wrong finding, for a genuinely different reason than any
of the seven cases above.

**What this shows:** the system's weak point isn't the judge's reasoning — it's the
paraphrase step's limited attention span. A short teach-back, by construction, can't
mention everything in a long document, and a planted risk can be silently dropped
rather than misread if something more dramatic (even if correctly understood)
crowds it out. The judge can only compare what's in front of it; if the paraphrase
never engages with a buried instruction, there is nothing there to catch.

**What's still needed before this could be trusted on a real patient:** (1) a
paraphrase step that produces (or an architecture that runs) multiple independent
teach-back samples per document, or a longer teach-back for longer documents, so a
buried instruction has a real chance of surfacing; (2) a reviewer-facing signal
distinguishing "the judge compared against a complete paraphrase and found nothing"
from "the paraphrase may not have engaged with parts of the source" — right now a
silent drop and a genuinely clean paraphrase look identical to the reviewer unless
they open the full transcript; and (3) validation by a health-literacy specialist on
whether 2–5 sentences is even the right length for a teach-back of a long leaflet, or
whether real patients drop the same content for the same reason — which would make
this a fair reflection of real risk, not just an artefact of our prompt design.

## Reader panel vs single reader (n=12, header stripped)

Reproduce with `.venv/bin/python -m src.panel_eval` (writes `outputs/panel_results.csv`,
`outputs/panel_summary.csv`, and every teach-back and judge output to
`outputs/panel_runs.json`; console log in `outputs/panel_eval_log.txt`).

**What changed from the locked run.** (1) Each file's header is stripped before any
model call ([src/documents.py](src/documents.py)), so neither the reader nor the judge
can see the answer key. (2) Alongside the original single reader, a **reader panel**
([src/panel.py](src/panel.py)) runs the same teach-back with five simulated readers
defined by reading behaviour only: a skimmer, limited health literacy, English as an
additional language (reads literally), an older adult on several medicines, and an
anxious reader focused on warnings. Each teach-back goes through the unchanged judge.
**Decision rule, fixed before this run:** the panel flags a document if any reader is
flagged. Both methods ran fresh, on the same 12 documents, once each, no retries.

| Method | Subset | Caught | False alarms | Mean cost/doc (CLI-reported) | Mean time/doc |
|---|---|---|---|---|---|
| Single reader | primary (n=8) | 3/4 | 1/4 | $0.026 | 31.7s |
| **Reader panel (5)** | primary (n=8) | **4/4** | 1/4 | $0.125 | 33.5s |
| Readability baseline | primary (n=8) | 4/4 | 4/4 | — | — |
| Single reader | all 12 | 4/7 | 1/5 | $0.025 | 30.5s |
| **Reader panel (5)** | all 12 | **6/7** | **2/5** | $0.124 | 32.4s |
| Readability baseline | all 12 | 7/7 | 5/5 | — | — |

| doc_id | planted? | single | panel | readers that misread (of 5) |
|---|---|---|---|---|
| `pil_amoxicillin` | no | **flagged (false alarm)** | **flagged (false alarm)** | 2: limited literacy, second language |
| `nhs_antibiotics` | no | clear | clear | 0 |
| `nhs_paracetamol` | no | clear | clear | 0 |
| `nhs_ibuprofen` | no | clear | clear | 0 |
| `synthetic_paracetamol_duration_reversed` | yes | caught | caught | 5 |
| `synthetic_ibuprofen_duration_reversed` | yes | caught | caught | 5 |
| `synthetic_amoxicillin_misseddose` | yes | **missed** | caught | 2: skimmer, older adult |
| `synthetic_antibiotics_doubledose` | yes | caught | caught | 3 |
| `synthetic_ibuprofen_nsaid_softened` (edge) | yes | **missed** | **missed** | 0 |
| `synthetic_amoxicillin_driving_stacked_negation` (edge control) | no | clear | **flagged (false alarm)** | 2: skimmer, limited literacy |
| `synthetic_amoxicillin_kidney_selfadjust` (edge) | yes | caught | caught | 1: older adult |
| `synthetic_amoxicillin_fulltext_buried` (edge, the documented failure) | yes | **missed** | **caught** | 3: skimmer, second language, anxious |

**Measured improvement and its trade-off.** On these 12 documents the panel caught 6
of 7 planted risks against the single reader's 4 of 7. That includes the documented
failure case above, the missed-dose risk buried in the full leaflet, which three of
five readers surfaced. The cost: one more false alarm (2/5 clean documents flagged
vs 1/5) and about 5× the model spend per document (CLI-reported $0.124 vs $0.025;
roughly $0.035–0.05 at direct-API prices using the estimate below). Wall-clock time
barely moves (+2s), because the five readers run in parallel.

**What the false alarms were.** Both are low-severity (2–3) flags on the same real
leaflet wording, "Space the doses evenly during the day, at least 4 hours apart": the
readers turned a *minimum* gap into a *target* schedule. That is arguably a genuine
ambiguity in the real leaflet, not judge noise, but it is not a planted risk, so it is
scored as a false alarm. In the web UI this is the case the **Dismiss with a reason**
action exists for.

**What this rerun also shows about the locked numbers.** On header-stripped input,
the original single reader caught 3/4 primary planted cases (locked: 4/4) with 1/4
false alarms (locked: 0/4), and its catches came with noticeably lower confidence
(e.g. paracetamol 0.55–0.7 per reader here vs 0.95 locked). With one run per document
we cannot separate how much of the gap is the leak and how much is ordinary
run-to-run variation. Either way, the locked numbers should not be quoted without
this caveat.

**Not tuned, and what we did not do.** Severity does not separate the false alarms
from true catches in this run (true catches scored 2–4, false alarms 2–3), so we did
not add a threshold. We also did not change the "any reader" rule after seeing these
results. Choosing a rule such as "2 or more readers" now would be fitting it to
these 12 documents. Any new rule needs testing on new, held-out cases. The
`nsaid_softened` miss (a prohibition softened into "people sometimes combine...")
was missed by all five readers, which suggests a different reader is not the fix
there.

## Who reviews flagged cases

See [README.md § Who reviews flagged cases](README.md#who-reviews-flagged-cases-and-who-can-override).
Every flag — including the low-confidence, wrong-reason flag above — lands in the
same review queue a human reviewer works through; nothing is auto-rejected or
auto-approved. The failure case above is also an argument *for* that design: even
when the method caught the wrong thing, it still surfaced *something* for a human to
look at, rather than silently passing the document as clean.

## Cost estimate

Two different numbers, for two different purposes:

**1. What this demo actually spent.** The team's Anthropic API key had no credit
balance and the team did not want to pay for a separate API top-up, so the paraphrase
and judge calls in this repository run through the Claude Code CLI
([src/claude_cli.py](src/claude_cli.py)) authenticated against a Claude subscription,
not a metered API key — disclosed in the README's AI-disclosure section. The CLI
reports a "list price"-equivalent cost per call, which includes its own agent-harness
system-prompt overhead (tens of thousands of tokens on a cold cache, amortized via
Anthropic's prompt caching on repeat calls with the same system prompt). Measured
across the primary 8-document run: **$0.2096 total, ~$0.026/document average**
(`outputs/results.csv`, `run_cost_usd` column).

**2. What a production deployment would actually cost.** A real integration would
call the Anthropic API directly (`anthropic` Python SDK, no agent harness), paying
only for the document text, our prompts, and the model's response — no harness
overhead. Based on this project's actual document lengths (roughly 500–900 words) and
Anthropic's published API pricing (checked 2026-10-17: Claude Haiku 4.5 $1.00/$5.00
per million input/output tokens for the paraphrase step, Claude Sonnet 5 $2.00/$10.00
per million input/output tokens for the judge step), a per-document check comes to
roughly **$0.007–0.01**.

**Human reviewer time, for comparison.** A qualified reviewer (e.g. a
medicines-information pharmacist or health-literacy lead) reading one patient
document closely enough to catch a subtle misunderstanding risk — not just
proofreading — plausibly takes 10–15 minutes. At an illustrative fully-loaded UK
clinical-pharmacist staff cost of roughly £40–50/hour (not independently sourced for
this project; a real pricing conversation would use the buyer's own staff-cost
figures), that is on the order of **£7–12 (~$9–15) of reviewer time per document**,
for every document, regardless of whether it has a problem. The AI check does not
replace that review — it is designed to concentrate it: the reviewer still makes the
final call on every *flagged* document, but no longer has to closely read every
*clean* one looking for a needle that usually isn't there.

**Proposed pricing.** A per-document fee of **$2–5 per document checked**, or a
monthly plan around **$200–500/month covering up to ~100 documents**, comfortably
covers the ~$0.01/document compute cost plus the review-queue tooling, audit trail,
and source-citation infrastructure around it, while remaining far cheaper than the
reviewer time it's designed to concentrate rather than replace.

## No claim beyond what these numbers support

On this 8-document labelled test set plus 4 additional hand-built edge cases, this
tool caught 7 of 8 planted misunderstandings by the strict "named the actual planted
risk" standard, with zero false positives across 6 clean/control documents. We do not
claim this generalises beyond these 12 documents, that it is "safe" or "compliant" for
real patient use, or that it would perform this well on a larger, independently
labelled test set. See "Honest limits" in [README.md](README.md).

Those figures come from the locked run, which had the answer-key header visible to
the models. On the header-stripped rerun, the single reader caught 4 of 7 with 1 false
alarm in 5, and the reader panel caught 6 of 7 with 2 false alarms in 5. See
[Reader panel vs single reader](#reader-panel-vs-single-reader-n12-header-stripped).
