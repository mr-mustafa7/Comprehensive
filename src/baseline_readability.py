"""Baseline comparator, required by the track brief: a plain readability-score flag.

This baseline does NOT read for meaning. It scores how hard the text is to read
(sentence length, syllables per word) and flags a document if it sits above a
threshold associated with "harder than general-public reading level" — a common
rule of thumb used in plain-English health-literacy guidance is to target
roughly a 9th-to-11th-UK-school-year reading age (approx. US grade 6-8 on the
Flesch-Kincaid scale). We use a slightly looser threshold (grade > 9) so the
baseline isn't trivially tripped by every medical document.

The point of comparing against this baseline is exactly that it is naive: it cannot
tell a reversed instruction from a correct one if both are written in equally simple
words, which is precisely the gap the LLM paraphrase+judge pipeline is built to catch.
"""

from pathlib import Path

import nltk
import textstat

# textstat's syllable counter pulls NLTK's CMU Pronouncing Dictionary, downloading
# it over the network (and failing hard on machines without a working CA bundle,
# as this one did mid-build) unless it's already present. Bundled locally under
# nltk_data/ so this works offline on a fresh clone — see README credits for the
# dictionary's license.
_BUNDLED_NLTK_DATA = str(Path(__file__).resolve().parent.parent / "nltk_data")
if _BUNDLED_NLTK_DATA not in nltk.data.path:
    nltk.data.path.insert(0, _BUNDLED_NLTK_DATA)

FK_GRADE_THRESHOLD = 9.0
SMOG_THRESHOLD = 9.0


def baseline_flag(document_text: str) -> dict:
    """Score document_text for readability and flag it if above threshold."""
    fk_grade = textstat.flesch_kincaid_grade(document_text)
    smog = textstat.smog_index(document_text)
    flagged = (fk_grade > FK_GRADE_THRESHOLD) or (smog > SMOG_THRESHOLD)
    return {
        "flesch_kincaid_grade": fk_grade,
        "smog_index": smog,
        "flagged": flagged,
    }
