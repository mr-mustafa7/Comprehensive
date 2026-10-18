"""Transcribe a photographed or scanned document image to plain text.

Operator-side input only: a reviewer photographs or scans a printed document as
an alternative to picking from the test-set list. No patient is involved, and
nothing about a real person is stored — this is the same document-text input the
existing pipeline already takes, just sourced from an image instead of a .txt
file. The transcription is always shown back to the reviewer to confirm or edit
before any check runs — this step is not trusted blindly.
"""

from src.claude_cli import call_claude_with_image

TRANSCRIBE_MODEL_ALIAS = "haiku"

PROMPT = """Transcribe every word of visible text in this image of a patient \
information document (a medicine leaflet, discharge note, or similar), exactly \
as written, preserving line breaks and section structure as best you can from \
the layout. Do not summarise, correct, simplify, or translate anything. If the \
image is blurry, cut off, at an angle, or you are not confident in part of the \
transcription, include your best reading anyway rather than omitting it, since \
a human reviewer will check this transcription before it is used for anything.

Respond with ONLY the transcribed text — no preamble, no commentary, no markdown \
formatting."""

_LOW_CONFIDENCE_MARKERS = (
    "i cannot", "i'm unable", "i am unable", "no text", "cannot see",
    "can't make out", "not legible", "too blurry",
)


class TranscriptionError(RuntimeError):
    pass


def transcribe(image_bytes: bytes, media_type: str) -> dict:
    """Return {"text": str, "low_confidence": bool, "cost_usd": float}."""
    text, usage = call_claude_with_image(PROMPT, image_bytes, media_type, TRANSCRIBE_MODEL_ALIAS)
    text = text.strip()
    lowered = text.lower()
    low_confidence = len(text) < 20 or any(marker in lowered for marker in _LOW_CONFIDENCE_MARKERS)
    return {
        "text": text,
        "low_confidence": low_confidence,
        "cost_usd": usage.get("cost_usd", 0.0),
    }
