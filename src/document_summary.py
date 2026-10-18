"""Patient-friendly summaries of immutable approved medication documentation."""

from __future__ import annotations

import json
import re
from functools import lru_cache

from src.claude_cli import call_claude


def _structured_summary(assignment: dict) -> dict:
    quantity = assignment["dose_quantity"]
    quantity_text = str(int(quantity)) if float(quantity).is_integer() else f"{quantity:g}"
    points = [
        f"Take {quantity_text} {assignment['dose_unit']} each time.",
        f"The recorded frequency is {assignment['frequency_per_day']} time(s) per day.",
        f"Timing: {assignment['timing_instructions']}",
    ]
    if assignment.get("conditions"):
        points.append(f"Conditions or exceptions: {assignment['conditions']}")
    return {
        "overview": (
            f"This is a plain-language guide to the clinician-approved documentation "
            f"for {assignment['medication_name']}."
        ),
        "key_points": points,
        "important_information": (
            f"It applies from {assignment['effective_from']} and is tied to approved "
            f"document version {assignment['version_number']}."
        ),
        "generated_by": "structured",
    }


@lru_cache(maxsize=128)
def _claude_summary(payload_json: str) -> dict:
    system = """Explain clinician-approved medication documentation in plain language.
Use only the supplied content. Do not diagnose, recommend treatment, change a dose,
or invent missing information. Return JSON only:
{"overview":"one short paragraph","key_points":["three to five concise points"],
"important_information":"one short paragraph"}
Clearly preserve quantities, units, frequency, timing, conditions, and version details."""
    raw, _ = call_claude(system, payload_json, "sonnet")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    value = json.loads(text)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("overview"), str)
        or not isinstance(value.get("key_points"), list)
        or not all(isinstance(point, str) for point in value["key_points"])
        or not isinstance(value.get("important_information"), str)
    ):
        raise ValueError("invalid document summary response")
    value["generated_by"] = "ai"
    return value


def summarize_assignment(assignment: dict, use_ai: bool = False) -> dict:
    """Return an AI summary when enabled, with a safe structured fallback."""
    if use_ai:
        payload = {
            "medication_name": assignment["medication_name"],
            "approved_document_version": assignment["version_number"],
            "approved_document_text": assignment["instruction_text"],
            "quantity_each_time": assignment["dose_quantity"],
            "dose_unit": assignment["dose_unit"],
            "frequency_per_day": assignment["frequency_per_day"],
            "timing": assignment["timing_instructions"],
            "conditions_or_exceptions": assignment["conditions"],
            "effective_from": assignment["effective_from"],
        }
        try:
            return _claude_summary(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        except Exception:
            pass
    return _structured_summary(assignment)
