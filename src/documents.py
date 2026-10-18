"""Split a source file into its provenance header and the document body.

Every file in data/sources/ starts with a metadata header (source URL, licence,
access date) ending in a line of just "---". Synthetic files' headers also contain
the answer key: the original sentence, the planted sentence, the risk type and the
ground-truth label. That header must never reach the simulated reader or the judge,
or the check is being shown the answer. Only the body is sent to a model; the
header is kept for display and provenance.
"""

from pathlib import Path

HEADER_END = "\n---\n"


def split_header(text: str) -> tuple[str, str]:
    """Return (header, body). Text with no "---" separator is all body."""
    head, sep, body = text.partition(HEADER_END)
    if not sep:
        return "", text
    return head.strip(), body.strip()


def read_body(path: Path) -> str:
    return split_header(path.read_text(encoding="utf-8"))[1]
