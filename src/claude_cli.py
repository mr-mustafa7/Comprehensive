"""LLM transport: calls Claude via the Claude Code CLI in non-interactive print mode,
authenticated against the user's own Claude subscription (not a separately-billed
Anthropic API key). Each call spawns `npx @anthropic-ai/claude-code -p ...` with all
built-in tools disabled, so it behaves as a plain one-shot text completion — the CLI
is used purely as an authenticated transport for a single prompt/response, not as an
agentic coding session.

This is a deliberate swap from the track brief's suggested "ANTHROPIC_API_KEY from
environment" path: the team's Anthropic API key had no credit balance and the team
did not want to pay for a separate API top-up, so the paraphrase and judge calls run
against the Claude Code subscription instead. Disclosed here and in the README.
"""

import base64
import json
import subprocess

CLI_COMMAND = ["npx", "-y", "@anthropic-ai/claude-code"]
CALL_TIMEOUT_SECONDS = 180
IMAGE_CALL_TIMEOUT_SECONDS = 90


class ClaudeCliError(RuntimeError):
    pass


def call_claude(system_prompt: str, user_prompt: str, model_alias: str) -> tuple[str, dict]:
    """Run one non-interactive Claude Code call and return (response_text, usage_dict).

    model_alias: a CLI model alias, e.g. "haiku" or "sonnet" (resolves to the latest
    generation of that tier).
    """
    cmd = CLI_COMMAND + [
        "-p", user_prompt,
        "--system-prompt", system_prompt,
        "--model", model_alias,
        "--output-format", "json",
        "--tools", "",
        "--no-session-persistence",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        raise ClaudeCliError(
            f"claude CLI exited {result.returncode}: {result.stderr.strip()[:500]}"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeCliError(
            f"could not parse CLI JSON output: {exc}\nstdout: {result.stdout[:500]!r}"
        ) from exc

    if data.get("is_error"):
        raise ClaudeCliError(f"claude CLI reported an error: {data}")

    text = data.get("result", "")
    usage = {
        "cost_usd": data.get("total_cost_usd", 0.0),
        "duration_ms": data.get("duration_ms", 0),
        "num_turns": data.get("num_turns", 1),
        "model_usage": data.get("modelUsage", {}),
    }
    return text, usage


def call_claude_with_image(prompt: str, image_bytes: bytes, media_type: str,
                            model_alias: str) -> tuple[str, dict]:
    """One non-interactive Claude Code call with an image attached, return
    (response_text, usage_dict).

    Tools are disabled the same as call_claude(), so this cannot read the image
    from a local file path (verified: it refuses and asks for the image to be
    attached to the conversation instead) — the image must be embedded as a real
    content block, which requires --input-format/--output-format stream-json
    rather than the plain -p positional-prompt path call_claude() uses.
    """
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    message = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": prompt},
            ],
        },
    }
    cmd = CLI_COMMAND + [
        "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--model", model_alias,
        "--tools", "",
        "--no-session-persistence",
    ]
    result = subprocess.run(
        cmd, input=json.dumps(message) + "\n", capture_output=True, text=True,
        timeout=IMAGE_CALL_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ClaudeCliError(
            f"claude CLI (image) exited {result.returncode}: {result.stderr.strip()[:500]}"
        )

    final = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            final = event

    if final is None:
        raise ClaudeCliError(
            f"claude CLI (image) produced no result event\nstdout: {result.stdout[:500]!r}"
        )
    if final.get("is_error"):
        raise ClaudeCliError(f"claude CLI (image) reported an error: {final}")

    text = final.get("result", "")
    usage = {
        "cost_usd": final.get("total_cost_usd", 0.0),
        "duration_ms": final.get("duration_ms", 0),
        "num_turns": final.get("num_turns", 1),
        "model_usage": final.get("modelUsage", {}),
    }
    return text, usage
