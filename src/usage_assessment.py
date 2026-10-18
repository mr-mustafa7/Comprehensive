"""Medication-usage comparison with deterministic checks and a swappable LLM adapter.

The structured regimen is the source of truth.  A general leaflet is supporting
context only.  Every failure is represented as ``analysis_incomplete`` so callers
cannot accidentally turn a transport or parsing error into a clean result.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from src.claude_cli import call_claude

VALID_STATES = {"no_discrepancy_detected", "review_required", "analysis_incomplete"}
REVIEW_MESSAGE = (
    "Your report may differ from the instructions recorded by your clinician. "
    "Do not change what you take based on this screen. Check the approved wording "
    "below and contact your clinician or pharmacist for advice. If you feel unwell "
    "or think you may need urgent help, use your usual urgent-care service."
)
INCOMPLETE_MESSAGE = (
    "We could not complete this comparison. Your report has been sent for clinician "
    "review. Do not change what you take based on this screen; contact your clinician "
    "or pharmacist if you are unsure what to do next."
)
CLEAR_MESSAGE = (
    "No difference was detected between the details you reported and the recorded "
    "instructions. This is not a medical safety decision. Contact your clinician or "
    "pharmacist if anything is unclear or if your circumstances have changed."
)


class UsageInferenceAdapter(Protocol):
    name: str

    def interpret(self, report: dict, regimen: dict, instruction_text: str) -> tuple[dict, dict]: ...


@dataclass
class ClaudeUsageAdapter:
    """Free-text interpretation through the repository's existing Claude CLI transport."""

    model_alias: str = "sonnet"
    name: str = "claude-cli:sonnet"

    def interpret(self, report: dict, regimen: dict, instruction_text: str) -> tuple[dict, dict]:
        system = """You compare a fictional patient's description of what they actually took
with their clinician-approved, patient-specific medication instructions. Do not diagnose,
triage, recommend treatment, change a dose, or invent instructions. Identify only possible
contradictions, ambiguity, timing differences, or relevant stated conditions. Return JSON only:
{"findings":[{"type":"free_text_contradiction|timing_mismatch|condition_or_restriction|ambiguous_report","reported_value":"...","approved_value":"...","evidence":"...","requires_clinician_review":true}],"summary":"..."}
Use an empty findings list when the free text adds no discrepancy. Evidence must quote or
closely paraphrase only the supplied report and approved instruction."""
        user = json.dumps(
            {
                "patient_report": {
                    "number_of_doses": report.get("number_of_doses"),
                    "quantity_per_dose": report.get("quantity_per_dose"),
                    "timing_information": report.get("timing_information", ""),
                    "explanation": report.get("explanation", ""),
                    "uncertain": bool(report.get("uncertain")),
                },
                "approved_regimen": {
                    "dose_quantity": regimen.get("dose_quantity"),
                    "dose_unit": regimen.get("dose_unit"),
                    "frequency_per_day": regimen.get("frequency_per_day"),
                    "timing_instructions": regimen.get("timing_instructions", ""),
                    "conditions": regimen.get("conditions", ""),
                },
                "approved_instruction": instruction_text,
            },
            ensure_ascii=False,
        )
        raw, usage = call_claude(system, user, self.model_alias)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("findings"), list):
            raise ValueError("model response is missing a findings list")
        allowed = {"free_text_contradiction", "timing_mismatch", "condition_or_restriction", "ambiguous_report"}
        for finding in parsed["findings"]:
            if not isinstance(finding, dict) or finding.get("type") not in allowed:
                raise ValueError("model response contains an invalid finding")
            finding["requires_clinician_review"] = True
        return parsed, usage


def _finding(kind: str, reported: Any, approved: Any, evidence: str) -> dict:
    return {
        "type": kind,
        "reported_value": "not provided" if reported is None else str(reported),
        "approved_value": "not provided" if approved is None else str(approved),
        "evidence": evidence,
        "requires_clinician_review": True,
    }


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _text_dose_count(text: str) -> int | None:
    lowered = text.lower()
    # Check higher/explicit counts before "once": a sentence can say "twice,
    # once in the morning and once at night" and should resolve to two.
    word_counts = {"four times": 4, "three times": 3, "twice": 2, "once": 1}
    for phrase, count in word_counts.items():
        if phrase in lowered:
            return count
    if "morning and night" in lowered or "morning and evening" in lowered:
        return 2
    match = re.search(r"\b([1-9])\s+(?:times|doses?)\b", lowered)
    return int(match.group(1)) if match else None


def rules_only_baseline(report: dict, regimen: dict) -> dict:
    """Simple comparator used as the declared baseline in held-out evaluation."""
    types: list[str] = []
    doses = _as_int(report.get("number_of_doses"))
    expected_doses = _as_int(regimen.get("frequency_per_day"))
    quantity = _as_float(report.get("quantity_per_dose"))
    expected_quantity = _as_float(regimen.get("dose_quantity"))
    if doses is not None and expected_doses is not None and doses != expected_doses:
        types.append("frequency_mismatch")
    if quantity is not None and expected_quantity is not None and abs(quantity - expected_quantity) > 1e-9:
        types.append("quantity_mismatch")
    return {"potential_discrepancy": bool(types), "discrepancy_types": types}


def assess_usage(
    report: dict,
    regimen: dict,
    instruction_text: str,
    adapter: UsageInferenceAdapter | None = None,
) -> dict:
    """Compare one actual-use report with its immutable approved regimen snapshot."""
    started = time.perf_counter()
    findings: list[dict] = []
    errors: list[str] = []

    approved_doses = _as_int(regimen.get("frequency_per_day"))
    approved_quantity = _as_float(regimen.get("dose_quantity"))
    reported_doses = _as_int(report.get("number_of_doses"))
    reported_quantity = _as_float(report.get("quantity_per_dose"))
    unit = (regimen.get("dose_unit") or "unit").strip()

    if not instruction_text.strip():
        errors.append("approved instruction text is missing")
    if approved_doses is None or approved_quantity is None or not unit:
        errors.append("approved regimen is incomplete")
    if reported_doses is None:
        findings.append(_finding("missing_information", None, approved_doses, "Number of doses was not provided."))
        errors.append("number of doses is missing or invalid")
    if reported_quantity is None:
        findings.append(_finding("missing_information", None, f"{approved_quantity} {unit}", "Quantity per dose was not provided."))
        errors.append("quantity per dose is missing or invalid")

    if reported_doses is not None and approved_doses is not None and reported_doses != approved_doses:
        findings.append(_finding(
            "frequency_mismatch", f"{reported_doses} dose(s)", f"{approved_doses} dose(s) per day",
            "The reported number of doses differs from the clinician-approved daily frequency.",
        ))
    if reported_quantity is not None and approved_quantity is not None and abs(reported_quantity - approved_quantity) > 1e-9:
        findings.append(_finding(
            "quantity_mismatch", f"{reported_quantity:g} {unit}", f"{approved_quantity:g} {unit}",
            "The reported quantity on each occasion differs from the approved quantity.",
        ))

    explanation = (report.get("explanation") or "").strip()
    timing = (report.get("timing_information") or "").strip()
    if report.get("uncertain"):
        findings.append(_finding(
            "ambiguous_report", "patient selected uncertain / incomplete memory", "complete actual-use details",
            "The patient explicitly said that some details may be uncertain.",
        ))
        errors.append("patient marked the report as uncertain")
    if re.search(r"\b(not sure|unsure|can't remember|cannot remember|maybe|might have|forgot)\b", explanation.lower()):
        findings.append(_finding(
            "ambiguous_report", explanation, "complete actual-use details",
            "The written description contains uncertainty language.",
        ))
        errors.append("free text is ambiguous")

    text_count = _text_dose_count(explanation)
    if text_count is not None and reported_doses is not None and text_count != reported_doses:
        findings.append(_finding(
            "structured_text_contradiction", f"structured: {reported_doses}; text suggests: {text_count}",
            f"internally consistent report (approved: {approved_doses})",
            "The structured dose count and written description appear to disagree.",
        ))

    usage = {"cost_usd": 0.0, "duration_ms": 0, "num_turns": 0}
    model_name = "deterministic-usage-comparator-v1"
    if adapter is not None and explanation:
        model_name = adapter.name
        try:
            interpreted, usage = adapter.interpret(report, regimen, instruction_text)
            model_usage = usage.get("model_usage") or {}
            if isinstance(model_usage, dict) and model_usage:
                model_name = f"{adapter.name} ({', '.join(sorted(model_usage))})"
            existing = {(f.get("type"), f.get("evidence")) for f in findings}
            for finding in interpreted["findings"]:
                marker = (finding.get("type"), finding.get("evidence"))
                if marker not in existing:
                    findings.append(finding)
                    existing.add(marker)
        except Exception as exc:  # fail closed on transport, parse, or validation errors
            errors.append(f"model inference failed: {exc}")

    # Missing/uncertain/model-error comparisons remain incomplete even if a separate
    # deterministic discrepancy was found. Both facts stay visible in findings.
    if errors:
        status = "analysis_incomplete"
    elif findings:
        status = "review_required"
    else:
        status = "no_discrepancy_detected"

    discrepancy_types = list(dict.fromkeys(f["type"] for f in findings))
    summary_parts = []
    if reported_doses is not None:
        summary_parts.append(f"{reported_doses} dose(s)")
    if reported_quantity is not None:
        summary_parts.append(f"{reported_quantity:g} {unit} each time")
    if timing:
        summary_parts.append(f"timing: {timing}")
    report_summary = ", ".join(summary_parts) or "The report did not contain enough structured detail."

    return {
        "status": status,
        "potential_discrepancy": bool(findings),
        "discrepancy_types": discrepancy_types,
        "patient_report_summary": report_summary,
        "approved_instruction_excerpt": instruction_text.strip(),
        "findings": findings,
        "patient_message": REVIEW_MESSAGE if status == "review_required" else INCOMPLETE_MESSAGE if status == "analysis_incomplete" else CLEAR_MESSAGE,
        "clinician_summary": (
            f"{len(findings)} potential issue(s) require review." if findings
            else "Structured details match; no discrepancy was detected."
        ),
        "analysis_complete": status != "analysis_incomplete",
        "model_name": model_name,
        "model_error": "; ".join(errors),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "cost_usd": float(usage.get("cost_usd", 0.0) or 0.0),
    }


def validate_assessment(value: dict) -> dict:
    """Validate an externally produced assessment; return a fail-closed result."""
    try:
        if value.get("status") not in VALID_STATES:
            raise ValueError("invalid assessment status")
        if not isinstance(value.get("findings"), list):
            raise ValueError("findings must be a list")
        if not isinstance(value.get("analysis_complete"), bool):
            raise ValueError("analysis_complete must be boolean")
        return value
    except (AttributeError, TypeError, ValueError) as exc:
        return {
            "status": "analysis_incomplete",
            "potential_discrepancy": False,
            "discrepancy_types": [],
            "patient_report_summary": "Comparison unavailable.",
            "approved_instruction_excerpt": "",
            "findings": [],
            "patient_message": INCOMPLETE_MESSAGE,
            "clinician_summary": "Assessment output was invalid and requires review.",
            "analysis_complete": False,
            "model_name": "unknown",
            "model_error": str(exc),
            "latency_ms": 0,
            "cost_usd": 0.0,
        }
