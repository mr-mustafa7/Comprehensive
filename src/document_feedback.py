"""Clinician-review-only suggestions for supplementary instruction wording."""

from __future__ import annotations


def suggest_improvement(instruction_text: str, assessment: dict, regimen: dict) -> dict | None:
    """Return a conservative draft without changing the approved regimen.

    The draft is a hypothesis about clarity, never a claim that wording caused a
    patient's behaviour. It is not published until a clinician approves it.
    """
    types = set(assessment.get("discrepancy_types", []))
    if not types.intersection({"frequency_mismatch", "quantity_mismatch", "structured_text_contradiction", "ambiguous_report"}):
        return None
    quantity = regimen.get("dose_quantity")
    unit = regimen.get("dose_unit", "unit")
    frequency = regimen.get("frequency_per_day")
    timing = (regimen.get("timing_instructions") or "at the time specified by your clinician").strip()
    if quantity is None or frequency is None:
        return None
    unit_label = unit if float(quantity) == 1 else f"{unit}s"
    frequency_label = "once" if int(frequency) == 1 else f"{int(frequency)} times"
    wording = f"Take {quantity:g} {unit_label} {frequency_label} per day, {timing}."
    return {
        "proposed_wording": wording,
        "rationale": (
            "A reported difference suggests the frequency or quantity wording may be worth investigating. "
            "This does not establish that the document caused the report. The draft restates only the "
            "existing clinician-approved regimen and requires clinician review."
        ),
        "source_instruction": instruction_text,
    }
