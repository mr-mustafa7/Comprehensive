"""Mark the source phrases the judge blamed, inside the full document text.

The judge is asked to copy the responsible phrase exactly, but models sometimes
change quote marks, spacing or capitalisation, or elide with "...". Matching
tolerates those differences only. If a phrase still can't be found, it is reported
back as unmatched so the page can say so, rather than highlighting a guess.
"""

import re

from markupsafe import Markup, escape

_APOSTROPHES = "['‘’]"
_QUOTES = "[\"“”]"
_STRIP = " \t\n\"'‘’“”.,;:…"


def _phrase_pattern(fragment: str) -> re.Pattern | None:
    words = fragment.strip(_STRIP).split()
    if not words:
        return None
    parts = []
    for word in words:
        token = re.escape(word)
        token = re.sub(r"['‘’]", _APOSTROPHES, token)
        token = re.sub(r"(\\\")|[“”\"]", _QUOTES, token)
        parts.append(token)
    return re.compile(r"\s+".join(parts), re.IGNORECASE)


def _fragments(phrase: str) -> list[str]:
    """Split an elided quote ("take two ... after food") into its quoted pieces."""
    pieces = re.split(r"\.\.\.|…", phrase)
    return [p for p in pieces if len(p.split()) >= 2] or [phrase]


def highlight(text: str, blamed: list[tuple[str, str]]) -> tuple[Markup, list[str]]:
    """blamed: (source_phrase, reader_name) pairs. Returns (marked-up HTML, unmatched phrases)."""
    spans: list[list] = []  # [start, end, set(reader names)]
    unmatched = []
    for phrase, reader in blamed:
        found = False
        for fragment in _fragments(phrase):
            pattern = _phrase_pattern(fragment)
            match = pattern.search(text) if pattern else None
            if match:
                spans.append([match.start(), match.end(), {reader}])
                found = True
        if not found and phrase not in unmatched:
            unmatched.append(phrase)

    spans.sort(key=lambda s: s[0])
    merged: list[list] = []
    for span in spans:
        if merged and span[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], span[1])
            merged[-1][2] |= span[2]
        else:
            merged.append(span)

    out, pos = [], 0
    for start, end, readers in merged:
        out.append(escape(text[pos:start]))
        names = ", ".join(sorted(readers))
        out.append(Markup('<mark class="blamed" title="Misread by: {}">{}</mark>').format(
            names, text[start:end]))
        pos = end
    out.append(escape(text[pos:]))
    return Markup("").join(out), unmatched
