"""Benchmark Claude Code via the terminal CLI (`claude -p`).

Runs the prompt through `claude -p "..." --output-format stream-json --verbose`
and extracts timing from the CLI's own `result` event, which reports:

- `ttft_ms`:         time to first token (ms)
- `duration_ms`:     total wall time (ms), measured by the CLI
- `duration_api_ms`: API-side duration (ms), excludes local overhead
- `usage`:           input/output token counts
- `total_cost_usd`:  estimated cost

Returns a dict per run that the runner aggregates.
"""

import json
import shutil
import subprocess
import time

MAX_ERROR_LEN = 200


def find_claude_cli() -> str:
    path = shutil.which("claude")
    if not path:
        raise RuntimeError("claude CLI not found on PATH")
    return path


def run_once(prompt: str, *, cli_path: str | None = None) -> dict:
    cli = cli_path or find_claude_cli()
    cmd = [
        cli, "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
    ]
    wall_start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {
            "error": "subprocess timed out after 300s",
            "wall_ms": round((time.perf_counter() - wall_start) * 1000, 1),
        }
    wall_end = time.perf_counter()

    if proc.returncode != 0:
        err = (proc.stderr.strip() or f"exit code {proc.returncode}")[:MAX_ERROR_LEN]
        return {
            "error": err,
            "wall_ms": round((wall_end - wall_start) * 1000, 1),
        }

    result_event = None
    first_assistant = None
    output_text = ""
    for line in proc.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result_event = event
            output_text = event.get("result", "")
        if event.get("type") == "assistant" and first_assistant is None:
            first_assistant = event

    if not result_event:
        return {
            "error": "no result event in stream-json output",
            "wall_ms": round((wall_end - wall_start) * 1000, 1),
        }

    usage = result_event.get("usage", {})
    return {
        "ttft_ms": result_event.get("ttft_ms"),
        "duration_ms": result_event.get("duration_ms"),
        "duration_api_ms": result_event.get("duration_api_ms"),
        "wall_ms": round((wall_end - wall_start) * 1000, 1),
        "input_tokens": usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0),
        "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "output_chars": len(output_text),
        "total_cost_usd": result_event.get("total_cost_usd"),
        "num_turns": result_event.get("num_turns"),
        "stop_reason": result_event.get("stop_reason"),
        "model": (first_assistant or {}).get("message", {}).get("model"),
    }


if __name__ == "__main__":
    import pprint
    result = run_once("What is 2+2?")
    pprint.pprint(result)
