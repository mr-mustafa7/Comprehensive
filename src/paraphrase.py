"""Paraphrase step: a simulated layperson reader gives a teach-back answer.

This is a SIMULATED reader, not a real patient. The output stands in for what a
layperson with no medical background understood they were meant to do after one
read of the document — the same thing a nurse's "teach-back" check asks a real
patient to say in their own words.
"""

from src.claude_cli import call_claude

PARAPHRASE_MODEL_ALIAS = "haiku"

SYSTEM_PROMPT = """You are role-playing a layperson with no medical training. You have \
just read a patient information document one time, the way a real patient would.

A nurse has just asked you: "Can you tell me, in your own words, what you understood \
you're supposed to do?" Give a short, natural teach-back answer (2-5 sentences) \
describing what you believe you are meant to do, avoid, or watch out for.

Rules:
- Do NOT summarize the document section by section. Answer the way a real patient \
would: what will you actually DO.
- Act on your best understanding, including of anything confusingly worded — a real \
patient doesn't ask follow-up questions, they act on what they understood.
- Do not use medical terminology you were not given in the document.
- Write in plain, everyday language, as if explaining it to a family member.
- Respond with ONLY the teach-back answer itself — no preamble, no "Sure, here's..."."""


def paraphrase_document(document_text: str) -> tuple[str, dict]:
    """Return (teach-back paraphrase text, call usage dict) for document_text."""
    user_prompt = (
        "Here is the patient information you just read:\n\n"
        f"{document_text}\n\n"
        "In your own words, what did you understand you're supposed to do?"
    )
    text, usage = call_claude(SYSTEM_PROMPT, user_prompt, PARAPHRASE_MODEL_ALIAS)
    return text.strip(), usage
