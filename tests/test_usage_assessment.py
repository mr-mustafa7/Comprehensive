import json

from src.usage_assessment import assess_usage, rules_only_baseline, validate_assessment


REGIMEN = {
    "dose_quantity": 1,
    "dose_unit": "tablet",
    "frequency_per_day": 1,
    "timing_instructions": "in the morning",
    "conditions": "ask the fictional clinic if unclear",
}
INSTRUCTION = "Take one tablet once per day in the morning."


def report(doses=1, quantity=1, explanation="I took one tablet once in the morning.", uncertain=False):
    return {
        "number_of_doses": doses,
        "quantity_per_dose": quantity,
        "timing_information": "morning",
        "explanation": explanation,
        "uncertain": uncertain,
    }


def test_correct_frequency_has_no_detected_discrepancy():
    result = assess_usage(report(), REGIMEN, INSTRUCTION)
    assert result["status"] == "no_discrepancy_detected"
    assert result["potential_discrepancy"] is False


def test_incorrect_quantity_and_frequency_are_both_found():
    result = assess_usage(report(doses=2, quantity=2, explanation="I took two tablets twice."), REGIMEN, INSTRUCTION)
    assert result["status"] == "review_required"
    assert {"frequency_mismatch", "quantity_mismatch"}.issubset(result["discrepancy_types"])


def test_ambiguous_and_missing_information_fail_closed():
    result = assess_usage(report(doses=None, quantity=None, explanation="I cannot remember, maybe once.", uncertain=True), REGIMEN, INSTRUCTION)
    assert result["status"] == "analysis_incomplete"
    assert result["analysis_complete"] is False
    assert "missing_information" in result["discrepancy_types"]
    assert "ambiguous_report" in result["discrepancy_types"]


def test_structured_free_text_contradiction_is_flagged():
    result = assess_usage(report(doses=1, explanation="I took it twice."), REGIMEN, INSTRUCTION)
    assert result["status"] == "review_required"
    assert "structured_text_contradiction" in result["discrepancy_types"]


class BrokenService:
    name = "broken-model"

    def interpret(self, report, regimen, instruction):
        raise RuntimeError("service unavailable")


class ParsingFailure:
    name = "bad-json-model"

    def interpret(self, report, regimen, instruction):
        raise json.JSONDecodeError("bad output", "x", 0)


def test_model_service_failure_is_incomplete_not_clean():
    result = assess_usage(report(), REGIMEN, INSTRUCTION, BrokenService())
    assert result["status"] == "analysis_incomplete"
    assert "service unavailable" in result["model_error"]


def test_model_parsing_failure_is_incomplete_not_clean():
    result = assess_usage(report(), REGIMEN, INSTRUCTION, ParsingFailure())
    assert result["status"] == "analysis_incomplete"
    assert result["analysis_complete"] is False


def test_invalid_external_assessment_fails_closed():
    result = validate_assessment({"status": "all_good", "findings": []})
    assert result["status"] == "analysis_incomplete"


def test_rules_baseline_only_checks_structured_fields():
    result = rules_only_baseline(report(doses=1, explanation="I took it twice."), REGIMEN)
    assert result["potential_discrepancy"] is False
