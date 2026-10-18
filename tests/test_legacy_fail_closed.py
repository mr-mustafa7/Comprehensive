from src import judge
from webapp import patient_view, store


def test_original_clinician_features_still_render(client, login):
    login(client, "clinician@demo.test", "DemoClinician!2026")
    for path in ("/document-testing", "/upload", "/queue", "/governance", "/eval"):
        response = client.get(path)
        assert response.status_code == 200, path


def test_malformed_legacy_judge_output_is_flagged_for_review(monkeypatch):
    monkeypatch.setattr(judge, "call_claude", lambda *args: ("not json", {"cost_usd": 0}))
    result = judge.judge_paraphrase("Take one once.", "I take one once.")
    assert result["flagged"] is True
    assert result["risk_type"] == "analysis_incomplete"
    assert result["analysis_complete"] is False


def test_flagged_retest_is_never_presented_as_ready(app):
    parent_result = {"flagged": True, "n_flagged": 1, "n_readers": 1, "n_errors": 0, "readers": [{"judge": {"flagged": True, "source_phrase": "once"}}]}
    parent_id = store.save_run({"title": "Synthetic", "doc_id": "x"}, "Take once", "single", parent_result, 0, 0)
    child_result = {"flagged": True, "n_flagged": 1, "n_readers": 1, "n_errors": 0, "readers": [{"judge": {"flagged": True, "source_phrase": "daily"}}]}
    store.save_run({"title": "Edited: Synthetic", "doc_id": "x"}, "Take daily", "single", child_result, 0, 0, parent_run_id=parent_id)
    store.record_decision(parent_id, "Test clinician", "edit", "Retested")
    assert patient_view.resolve(store.get_run(parent_id))["state"] == "not_ready"


def test_incomplete_retest_is_never_presented_as_ready(app):
    parent_result = {"flagged": True, "n_flagged": 1, "n_readers": 1, "n_errors": 0, "readers": [{"judge": {"flagged": True, "source_phrase": "once"}}]}
    parent_id = store.save_run({"title": "Synthetic", "doc_id": "y"}, "Take once", "single", parent_result, 0, 0)
    incomplete = {"flagged": False, "n_flagged": 0, "n_readers": 1, "n_errors": 1, "readers": [{"judge": None, "error": "model failed"}]}
    store.save_run({"title": "Edited: Synthetic", "doc_id": "y"}, "Take daily", "single", incomplete, 0, 0, parent_run_id=parent_id)
    store.record_decision(parent_id, "Test clinician", "edit", "Retested")
    assert patient_view.resolve(store.get_run(parent_id))["state"] == "not_ready"
