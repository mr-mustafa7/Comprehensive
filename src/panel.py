"""Reader panel: the same teach-back check, run by five different simulated readers.

One simulated reader gives one sample of how a document can be read. A real
patient population reads the same leaflet in different ways — someone skimming
between tasks, someone with limited health literacy, someone reading in a second
language. The panel runs the existing paraphrase -> judge step once per reader and
reports how many of them misread it.

The readers are SIMULATED, and are defined by reading behaviour only — never by
ethnicity, gender or any other sensitive trait. Results show how the workflow
behaves, not how any real group of people reads.

Decision rule (fixed before any panel run on the test set, not tuned against it):
the panel flags a document if ANY reader's teach-back is flagged by the judge.

Usage:
    python -m src.panel --doc data/sources/synthetic/synthetic_paracetamol_duration_reversed.txt
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.claude_cli import call_claude
from src.documents import read_body
from src.judge import judge_paraphrase
from src.paraphrase import PARAPHRASE_MODEL_ALIAS
from src.paraphrase import SYSTEM_PROMPT as BASE_PARAPHRASE_PROMPT

PERSONAS = [
    {
        "id": "skimmer",
        "name": "The skimmer",
        "description": "Reads quickly between other tasks; picks out headings and numbers.",
        "prompt": "You are busy and read the document quickly, the way most people read a "
                  "leaflet: you skim, pick out headings and numbers, and do not reread "
                  "sentences that are awkwardly worded.",
    },
    {
        "id": "limited_literacy",
        "name": "Limited health literacy",
        "description": "Finds long sentences and medical words hard; goes with the gist.",
        "prompt": "You find long sentences and medical words hard to follow. When a "
                  "sentence is complicated you go with the gist you picked up rather than "
                  "working out the exact meaning.",
    },
    {
        "id": "second_language",
        "name": "English as an additional language",
        "description": "Reads every word carefully and literally; idioms and negations are harder.",
        "prompt": "English is not your first language. You read every word carefully and "
                  "take sentences literally. Idioms, unusual phrasing and sentences with "
                  "more than one 'not' are harder for you to untangle.",
    },
    {
        "id": "older_polypharmacy",
        "name": "Older adult, several medicines",
        "description": "Takes several medicines already; relies on habits from those.",
        "prompt": "You are an older adult who already takes several regular medicines. You "
                  "read carefully but tend to fit new instructions into the routines you "
                  "already follow for your other medicines.",
    },
    {
        "id": "anxious",
        "name": "Anxious reader",
        "description": "Worried about side effects; attention drawn to warnings.",
        "prompt": "You are anxious about taking this medicine. Your attention is drawn to "
                  "warnings and side effects, and those are what you remember most clearly "
                  "afterwards.",
    },
]


def _persona_system_prompt(persona: dict) -> str:
    return f"{BASE_PARAPHRASE_PROMPT}\n\nAbout you: {persona['prompt']}"


def run_reader(document_text: str, persona: dict) -> dict:
    """Run one simulated reader: persona teach-back, then the unchanged judge step."""
    user_prompt = (
        "Here is the patient information you just read:\n\n"
        f"{document_text}\n\n"
        "In your own words, what did you understand you're supposed to do?"
    )
    paraphrase_text, paraphrase_usage = call_claude(
        _persona_system_prompt(persona), user_prompt, PARAPHRASE_MODEL_ALIAS
    )
    paraphrase_text = paraphrase_text.strip()
    judge_result = judge_paraphrase(document_text, paraphrase_text)
    judge_usage = judge_result.pop("_usage")
    return {
        "persona_id": persona["id"],
        "persona_name": persona["name"],
        "persona_description": persona["description"],
        "paraphrase": paraphrase_text,
        "judge": judge_result,
        "cost_usd": paraphrase_usage.get("cost_usd", 0.0) + judge_usage.get("cost_usd", 0.0),
    }


def run_panel(document_text: str, on_reader_done=None) -> list[dict]:
    """Run every persona in parallel. on_reader_done(reader_result) fires as each finishes.

    Returns reader results in PERSONAS order. A reader whose model call fails is
    returned with an "error" key rather than silently dropped.
    """
    results = {}
    with ThreadPoolExecutor(max_workers=len(PERSONAS)) as pool:
        futures = {pool.submit(run_reader, document_text, p): p for p in PERSONAS}
        for future in as_completed(futures):
            persona = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # one failed reader must not hide the other four
                result = {
                    "persona_id": persona["id"],
                    "persona_name": persona["name"],
                    "persona_description": persona["description"],
                    "paraphrase": "",
                    "judge": None,
                    "cost_usd": 0.0,
                    "error": str(exc),
                }
            results[persona["id"]] = result
            if on_reader_done:
                on_reader_done(result)
    return [results[p["id"]] for p in PERSONAS]


def panel_flagged(readers: list[dict]) -> bool:
    """Pre-registered decision rule: flag if any reader's teach-back was flagged."""
    return any(r.get("judge") and r["judge"].get("flagged") for r in readers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", required=True, help="Path to a document to run the panel on")
    args = parser.parse_args()

    document_text = read_body(Path(args.doc))

    t0 = time.time()
    readers = run_panel(document_text)
    elapsed = time.time() - t0

    for r in readers:
        print(f"\n--- {r['persona_name']} (simulated reader) ---")
        if r.get("error"):
            print(f"  ERROR: {r['error']}")
            continue
        print(f"  teach-back: {r['paraphrase']}")
        j = r["judge"]
        print(f"  flagged={j['flagged']} risk={j['risk_type']} severity={j['severity']} "
              f"confidence={j['confidence']}")
        if j.get("source_phrase"):
            print(f"  source phrase: {j['source_phrase']!r}")

    n_flagged = sum(1 for r in readers if r.get("judge") and r["judge"].get("flagged"))
    print(f"\n{n_flagged} of {len(readers)} simulated readers misread this document. "
          f"Panel flag: {panel_flagged(readers)}. {elapsed:.0f}s, "
          f"CLI-reported cost ${sum(r['cost_usd'] for r in readers):.4f}")


if __name__ == "__main__":
    main()
