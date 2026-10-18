"""Judge step: flags misunderstanding risk, not factual groundedness.

This is the core distinction of the project: a RAGAs-style groundedness checker asks
"is the paraphrase supported by the source text?" This judge asks a different
question: "does the paraphrase reveal that a lay reader is likely to act on a
misunderstanding of the source's instruction, even though every word in the source
is itself accurate?" A paraphrase can be perfectly grounded and still reveal a
dangerous misunderstanding (e.g. the reader states confidently that they should do
the opposite of what a reversed-sounding sentence actually meant).
"""

import json
import re

from src.claude_cli import call_claude

JUDGE_MODEL_ALIAS = "sonnet"

SYSTEM_PROMPT = """You are a clinical patient-safety reviewer. You will be given (1) a \
patient information document and (2) a teach-back paraphrase: what a layperson said \
they understood they were meant to do after reading it once.

Your job is NOT to check whether the paraphrase is factually grounded in the source \
(that is a separate, different kind of check). Your job is to catch MISUNDERSTANDING \
RISK: cases where the paraphrase reveals the reader likely misunderstood an \
instruction in a way that could lead to unsafe or incorrect action, even if every \
word in the source document is itself accurate.

Look specifically for:
- reversed_instruction: the reader's stated plan is the opposite of what the source \
actually says to do
- dropped_condition: the reader missed a condition, exception, dose limit, or \
duration limit that changes what they should do
- ambiguous_negation: a double negative or ambiguous "not"/"don't" in the source that \
the reader resolved incorrectly
- dangerous_confidence: the reader states a confident, unconditional action where the \
source was conditional or said to check with a doctor/pharmacist first

Respond with ONLY a JSON object, no markdown code fences, no commentary before or \
after, in exactly this shape:
{
  "flagged": true or false,
  "risk_type": one of "reversed_instruction", "dropped_condition", "ambiguous_negation", "dangerous_confidence", "none",
  "severity": integer 1-5 (1 = trivial wording nitpick, 5 = could cause serious harm if acted on as stated),
  "confidence": number between 0.0 and 1.0,
  "source_phrase": the exact short phrase copied from the source document that is responsible (empty string if not flagged),
  "explanation": one or two sentence explanation of the specific misunderstanding risk (empty string if not flagged)
}

If the paraphrase correctly reflects the source's intent, flagged must be false — even \
if the paraphrase is informal, casual, or leaves out non-safety-critical detail. Only \
flag a genuine misunderstanding that would change what the reader does, not a \
stylistic or completeness difference."""


def _parse_json_response(raw_text: str) -> dict:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def judge_paraphrase(document_text: str, paraphrase_text: str) -> dict:
    """Compare paraphrase against source and return a structured misunderstanding-risk flag."""
    user_prompt = (
        f"SOURCE DOCUMENT:\n{document_text}\n\n"
        f"LAYPERSON TEACH-BACK PARAPHRASE:\n{paraphrase_text}\n\n"
        "Evaluate for misunderstanding risk and respond with the JSON object only."
    )
    raw_text, usage = call_claude(SYSTEM_PROMPT, user_prompt, JUDGE_MODEL_ALIAS)

    try:
        result = _parse_json_response(raw_text)
    except json.JSONDecodeError:
        result = {
            "flagged": False,
            "risk_type": "none",
            "severity": 0,
            "confidence": 0.0,
            "source_phrase": "",
            "explanation": f"JUDGE_PARSE_ERROR: could not parse model output: {raw_text[:200]!r}",
        }
    result["_usage"] = usage
    return result
