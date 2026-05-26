"""Benchmark Claude Code through NBI's WebSocket chat endpoint.

Connects to `ws://host:port/notebook-intelligence/copilot`, sends a
chat-request message, and measures timing from the outside:

- `ttft_ms`:      time from message-send to first content chunk
- `wall_ms`:      time from message-send to stream-end signal
- `output_chars`: total characters in the streamed assistant reply

JupyterLab must be running with NBI installed and Claude mode enabled.
The server token (if any) must be empty or passed via `--token`.

Protocol notes (from extension.py):
- Streaming chunks arrive as JSON with `choices[0].delta.nbiContent`
  where `nbiContent.type` is "markdown", "markdown_part", etc.
- The finish signal is `{"type": "stream-end", ...}`.
- Heartbeats arrive as `{"type": "claude-code-heartbeat", ...}`.
"""

import asyncio
import json
import time
import uuid

try:
    import websockets
except ImportError:
    websockets = None


async def run_once_async(
    prompt: str,
    *,
    host: str = "localhost",
    port: int = 8889,
    token: str = "",
) -> dict:
    if websockets is None:
        return {"error": "websockets package not installed (pip install websockets)"}

    url = f"ws://{host}:{port}/notebook-intelligence/copilot"
    if token:
        url += f"?token={token}"

    chat_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    request = json.dumps({
        "id": message_id,
        "type": "chat-request",
        "data": {
            "chatId": chat_id,
            "prompt": prompt,
            "language": "python",
            "filename": "benchmark.py",
            "chatMode": "ask",
            "toolSelections": {},
            "additionalContext": [],
        },
    })

    first_content_time = None
    total_chars = 0
    finished = False
    error_msg = None

    wall_start = time.perf_counter()

    try:
        async with websockets.connect(url, close_timeout=5, max_size=10 * 1024 * 1024) as ws:
            await ws.send(request)

            while not finished:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=120)
                except asyncio.TimeoutError:
                    error_msg = "timed out waiting for response (120s)"
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                # NBI stream-end signal
                if msg_type == "stream-end":
                    finished = True
                    continue

                # Heartbeat (ignore for timing, but proves the connection is alive)
                if msg_type == "claude-code-heartbeat":
                    continue

                # Streaming content: wrapped as
                # {"type": "stream-message", "data": {"choices": [...]}}
                data = msg.get("data") or {}
                choices = data.get("choices") if isinstance(data, dict) else None
                if isinstance(choices, list) and choices:
                    delta = choices[0].get("delta", {})
                    nbi = delta.get("nbiContent", {})
                    nbi_type = nbi.get("type")

                    if nbi_type in ("markdown", "markdown-part"):
                        content = nbi.get("content", "")
                        if content and first_content_time is None:
                            first_content_time = time.perf_counter()
                        total_chars += len(content)

    except Exception as e:
        error_msg = str(e)

    wall_end = time.perf_counter()
    wall_ms = round((wall_end - wall_start) * 1000, 1)

    if error_msg:
        return {"error": error_msg, "wall_ms": wall_ms}

    ttft_ms = (
        round((first_content_time - wall_start) * 1000, 1)
        if first_content_time
        else None
    )

    return {
        "ttft_ms": ttft_ms,
        "wall_ms": wall_ms,
        "output_chars": total_chars,
    }


def run_once(
    prompt: str,
    *,
    host: str = "localhost",
    port: int = 8889,
    token: str = "",
) -> dict:
    return asyncio.run(
        run_once_async(prompt, host=host, port=port, token=token)
    )


if __name__ == "__main__":
    import pprint
    result = run_once("What is 2+2?")
    pprint.pprint(result)
