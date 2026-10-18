"""Resolve what a patient would eventually see for a given run, and why.

This does not reformat or simplify the document text — it shows the actual
reviewed text, plus the flagged phrases that led to it, built entirely from
data this project already has (a run's stored result and its reviewer
decisions). No new model call, no new evaluation surface.
"""

from webapp import store


def flagged_phrases(run: dict) -> list[str]:
    seen, phrases = set(), []
    for reader in run["result"].get("readers", []):
        judge = reader.get("judge") or {}
        phrase = judge.get("source_phrase")
        if judge.get("flagged") and phrase and phrase not in seen:
            seen.add(phrase)
            phrases.append(phrase)
    return phrases


def resolve(run: dict) -> dict:
    """Return what to show for this run's patient view.

    state: "ready" (there is a reviewed document to show), "clean" (never
    flagged, shown as-is), or "not_ready" (reviewer hasn't resolved it yet).
    """
    if run["status"] == store.NOT_FLAGGED:
        return {"state": "clean", "text": run["document_text"], "flagged_phrases": []}

    if run["status"] == store.DISMISSED:
        decisions = store.get_decisions(run["id"])
        reason = next((d["reason"] for d in reversed(decisions) if d["action"] == "dismiss"), "")
        return {
            "state": "ready",
            "text": run["document_text"],
            "flagged_phrases": flagged_phrases(run),
            "reviewer_note": f"Reviewer judged the flagged wording clear enough to leave as-is: “{reason}”" if reason else "Reviewer judged the flagged wording clear enough to leave as-is.",
        }

    if run["status"] == store.EDITED:
        children = store.get_children(run["id"])
        if children:
            final = children[-1]
            return {
                "state": "ready",
                "text": final["document_text"],
                "flagged_phrases": flagged_phrases(run),
                "reviewer_note": "Reviewer rewrote the flagged wording; shown below is their corrected version, retested by the same readers.",
                "retest_flagged": bool(final["result"]["flagged"]),
            }

    return {"state": "not_ready", "text": None, "flagged_phrases": flagged_phrases(run)}
