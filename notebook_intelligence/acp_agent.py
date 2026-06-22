# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Codex agent mode over the Agent Client Protocol (issue #378, Phase 1).

A second, off-by-default agent mode that drives the chat panel like Claude mode
for the core loop (streaming, tool-call cards with diffs, per-tool approval),
backed by ``codex-acp`` over ACP instead of the Claude SDK.

Design notes (validated by the Phase 0 spike under ``spikes/acp-codex/``):

- The ACP client runs on its own worker thread with an asyncio loop, mirroring
  ``ClaudeCodeClient``. Per-request ``query`` blocks on that loop via
  ``run_coroutine_threadsafe`` while tool-call cards stream and ``request_permission``
  is answered cross-thread through ``wait_for_chat_user_input`` (the same poll a
  signal pattern Claude uses).
- ``agent-client-protocol`` is imported here, and this module is only imported
  when Codex mode is enabled, so the dependency loads lazily (matching #370).
- Phase 1 is deliberately allowed to duplicate a little of Claude's card/diff
  wiring; Phase 2 extracts the shared layer.
"""

import asyncio
import base64
import concurrent.futures
import difflib
import logging
import os
import sys
import threading
import time
from typing import Any, Optional

import acp
from acp import schema

from notebook_intelligence.api import (
    ChatCommand,
    ChatRequest,
    ChatResponse,
    Host,
    MarkdownData,
    ProgressData,
    ToolCallData,
    ConfirmationData,
)
from notebook_intelligence.base_chat_participant import BaseChatParticipant
from notebook_intelligence.util import ThreadSafeWebSocketConnector, get_jupyter_root_dir

log = logging.getLogger(__name__)

CODEX_AGENT_CHAT_PARTICIPANT_ID = "codex"
# Pinned in Phase 1 (the version the spike validated); revisit per release.
CODEX_ACP_PACKAGE = "@zed-industries/codex-acp@0.16.0"
_START_TIMEOUT = 60          # seconds to bring up codex-acp + a session
_RESPONSE_TIMEOUT = 30 * 60  # a turn can be long; cap so the UI doesn't hang forever
_POLL = 0.2

# The OpenAI mark, matching style/icons/openai.svg. Rendered as an <img> in the
# chat (the response avatar), so the fill is pinned to OpenAI blue rather than
# currentColor, mirroring how the Claude participant pins Anthropic orange.
_CODEX_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" fill="#0a84ff" fill-rule="evenodd" '
    'viewBox="0 0 24 24" width="24" height="24">'
    '<path clip-rule="evenodd" d="M8.086.457a6.105 6.105 0 013.046-.415c1.333.153 '
    '2.521.72 3.564 1.7a.117.117 0 00.107.029c1.408-.346 2.762-.224 4.061.366l.063.03'
    '.154.076c1.357.703 2.33 1.77 2.918 3.198.278.679.418 1.388.421 2.126a5.655 5.655 '
    '0 01-.18 1.631.167.167 0 00.04.155 5.982 5.982 0 011.578 2.891c.385 1.901-.01 '
    '3.615-1.183 5.14l-.182.22a6.063 6.063 0 01-2.934 1.851.162.162 0 00-.108.102c-.255'
    '.736-.511 1.364-.987 1.992-1.199 1.582-2.962 2.462-4.948 2.451-1.583-.008-2.986-.587'
    '-4.21-1.736a.145.145 0 00-.14-.032c-.518.167-1.04.191-1.604.185a5.924 5.924 0 '
    '01-2.595-.622 6.058 6.058 0 01-2.146-1.781c-.203-.269-.404-.522-.551-.821a7.74 7.74 '
    '0 01-.495-1.283 6.11 6.11 0 01-.017-3.064.166.166 0 00.008-.074.115.115 0 '
    '00-.037-.064 5.958 5.958 0 01-1.38-2.202 5.196 5.196 0 01-.333-1.589 6.915 6.915 0 '
    '01.188-2.132c.45-1.484 1.309-2.648 2.577-3.493.282-.188.55-.334.802-.438.286-.12'
    '.573-.22.861-.304a.129.129 0 00.087-.087A6.016 6.016 0 015.635 2.31C6.315 1.464 '
    '7.132.846 8.086.457zm-.804 7.85a.848.848 0 00-1.473.842l1.694 2.965-1.688 2.848a.849'
    '.849 0 001.46.864l1.94-3.272a.849.849 0 00.007-.854l-1.94-3.393zm5.446 6.24a.849.849 '
    '0 000 1.695h4.848a.849.849 0 000-1.696h-4.848z"/></svg>'
)
CODEX_AGENT_ICON_URL = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(_CODEX_ICON_SVG.encode("utf-8")).decode("utf-8")
)

_MAX_DIFF_LINES = 60


def _diff_lines(old: str, new: str, max_lines: int = _MAX_DIFF_LINES) -> tuple[list[dict], bool]:
    """Line-level diff as typed lines for a tool-call card.

    Duplicated (minimally) from claude.py to keep this module independent of
    the Claude SDK import; the shared version is a Phase 2 extraction.
    """
    lines: list[dict] = []
    for raw in difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(), lineterm="", n=1
    ):
        if raw.startswith(("---", "+++", "@@")):
            continue
        if raw.startswith("+"):
            lines.append({"type": "add", "content": raw[1:]})
        elif raw.startswith("-"):
            lines.append({"type": "remove", "content": raw[1:]})
        else:
            lines.append({"type": "context", "content": raw[1:] if raw[:1] == " " else raw})
    truncated = len(lines) > max(0, max_lines)
    return lines[: max(0, max_lines)], truncated


# ACP tool kinds are finer than NBI's card-icon categories; collapse them.
_ACP_KIND_TO_NBI = {
    "read": "read", "search": "read", "fetch": "read",
    "edit": "edit", "delete": "edit", "move": "edit",
    "execute": "execute",
}


def _nbi_kind(acp_kind: Optional[str]) -> str:
    return _ACP_KIND_TO_NBI.get(acp_kind or "", "other")


def _nbi_status(acp_status: Optional[str]) -> str:
    if acp_status in ("completed", "failed"):
        return acp_status
    return "in_progress"  # pending / in_progress / None


def resolve_codex_acp_command() -> list[str]:
    """The command that launches codex-acp.

    ``NBI_CODEX_ACP_COMMAND`` overrides (shell-split); otherwise run the pinned
    package via ``npx``. Kept separate from the Claude CLI resolver because
    codex-acp is an npm package, not a binary on PATH.
    """
    override = os.environ.get("NBI_CODEX_ACP_COMMAND", "").strip()
    if override:
        import shlex
        return shlex.split(override)
    return ["npx", "-y", CODEX_ACP_PACKAGE]


def codex_approval_args(full_access: bool) -> list[str]:
    """Codex config overrides that pin its approval posture.

    Default (``full_access`` off) forces ``approval_policy = untrusted`` so
    Codex asks before anything beyond trusted read-only commands, surfacing the
    request through NBI's per-tool confirmation. ``full_access`` (gated by the
    force-off ``codex_full_access`` admin policy) lets it run unattended. The
    flag is honored by the codex-acp binary's ``-c key=value`` override, so it
    works for both API-key and ChatGPT-auth sessions.

    The override takes precedence over the codex config file. In the API-key
    path NBI also isolates ``CODEX_HOME`` (see ``_child_env``), so the config
    base is NBI-controlled and neither the workspace nor the user's ~/.codex is
    read. With ChatGPT auth, codex uses the user's own ~/.codex; the ``-c``
    pin still overrides its top-level approval_policy. See the admin guide for
    the residual caveat on shared deployments.
    """
    policy = "never" if full_access else "untrusted"
    return ["-c", f'approval_policy="{policy}"']


class _NbiAcpClient(acp.Client):
    """The editor side of ACP. Maps agent events onto NBI's chat surfaces."""

    def __init__(self, owner: "AcpAgentClient"):
        self._owner = owner
        self._tool_state: dict[str, dict] = {}

    @property
    def _response(self) -> Optional[ChatResponse]:
        return self._owner.current_response

    async def session_update(self, session_id, update, **kw):
        resp = self._response
        if resp is None:
            return
        su = getattr(update, "session_update", None)
        if su in ("tool_call", "tool_call_update"):
            self._emit_tool_call(resp, update)
        elif su == "agent_message_chunk":
            text = _block_text(getattr(update, "content", None))
            if text:
                resp.stream(MarkdownData(content=text))
        elif su == "agent_thought_chunk":
            text = _block_text(getattr(update, "content", None))
            if text:
                resp.stream(MarkdownData(reasoning_content=text))
        elif su == "available_commands_update":
            self._owner.available_commands = [
                getattr(c, "name", "") for c in (update.available_commands or [])
            ]

    def _emit_tool_call(self, resp: ChatResponse, update):
        tid = update.tool_call_id
        state = self._tool_state.setdefault(
            tid, {"kind": "other", "title": "", "status": "in_progress", "diffs": []}
        )
        if getattr(update, "kind", None) is not None:
            state["kind"] = _nbi_kind(update.kind)
        if getattr(update, "title", None):
            state["title"] = update.title
        if getattr(update, "status", None) is not None:
            state["status"] = _nbi_status(update.status)
        diffs = _diffs_from_content(getattr(update, "content", None))
        if diffs:
            state["diffs"] = diffs
        resp.stream(ToolCallData(
            id=tid,
            title=state["title"] or "Tool call",
            kind=state["kind"],
            status=state["status"],
            diffs=state["diffs"] or None,
        ))

    async def request_permission(self, options, session_id, tool_call, **kw):
        resp = self._response
        allow = next((o for o in options if o.kind == "allow_once"), None) \
            or next((o for o in options if str(o.kind).startswith("allow")), None)
        if resp is None or allow is None:
            # No UI to ask, or no allow option offered: fail closed (reject).
            return acp.RequestPermissionResponse(
                outcome=schema.DeniedOutcome(outcome="cancelled")
            )
        callback_id = f"acp-perm-{tool_call.tool_call_id}"
        title = getattr(tool_call, "title", None) or "Run this tool?"
        resp.stream(ConfirmationData(
            title="Codex tool call",
            message=(
                f"Approve: {title}?\n\n"
                "Codex decides which tools to ask about, so some actions may run "
                "without a prompt."
            ),
            confirmArgs={"id": resp.message_id, "data": {
                "callback_id": callback_id, "data": {"confirmed": True}}},
            cancelArgs={"id": resp.message_id, "data": {
                "callback_id": callback_id, "data": {"confirmed": False}}},
            confirmLabel="Approve",
            cancelLabel="Reject",
        ))
        user_input = await ChatResponse.wait_for_chat_user_input(resp, callback_id)
        if user_input.get("confirmed"):
            return acp.RequestPermissionResponse(
                outcome=schema.AllowedOutcome(outcome="selected", option_id=allow.option_id)
            )
        reject = next((o for o in options if o.kind == "reject_once"), None) \
            or next((o for o in options if str(o.kind).startswith("reject")), None)
        if reject is not None:
            return acp.RequestPermissionResponse(
                outcome=schema.AllowedOutcome(outcome="selected", option_id=reject.option_id)
            )
        return acp.RequestPermissionResponse(outcome=schema.DeniedOutcome(outcome="cancelled"))

    # fs/*: implemented so an agent that delegates file ops (e.g. claude-acp)
    # routes through NBI. codex-acp self-applies, so these may not fire for it.
    async def read_text_file(self, path, session_id, limit=None, line=None, **kw):
        try:
            with open(path, encoding="utf-8") as f:
                return acp.ReadTextFileResponse(content=f.read())
        except Exception as e:
            raise acp.RequestError.internal_error(str(e))

    async def write_text_file(self, content, path, session_id, **kw):
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return acp.WriteTextFileResponse()
        except Exception as e:
            raise acp.RequestError.internal_error(str(e))

    # terminal/*: not emulated in Phase 1 (Codex runs shell internally).
    async def create_terminal(self, command, session_id, **kw):
        raise acp.RequestError.method_not_found("terminal not supported")

    async def terminal_output(self, session_id, terminal_id, **kw):
        raise acp.RequestError.method_not_found("terminal not supported")

    async def wait_for_terminal_exit(self, session_id, terminal_id, **kw):
        raise acp.RequestError.method_not_found("terminal not supported")

    async def kill_terminal(self, session_id, terminal_id, **kw):
        return None

    async def release_terminal(self, session_id, terminal_id, **kw):
        return None


def _block_text(block) -> str:
    if block is None:
        return ""
    return getattr(block, "text", "") or ""


def _diffs_from_content(content) -> list[dict]:
    out: list[dict] = []
    remaining = _MAX_DIFF_LINES
    for c in content or []:
        if getattr(c, "type", None) != "diff":
            continue
        if remaining <= 0:
            break
        lines, truncated = _diff_lines(
            getattr(c, "old_text", "") or "", getattr(c, "new_text", "") or "",
            max_lines=remaining,
        )
        if lines:
            out.append({"path": getattr(c, "path", ""), "lines": lines, "truncated": truncated})
            remaining -= len(lines)
    return out


class AcpAgentClient:
    """Persistent ACP client: one codex-acp subprocess + session on a worker
    thread, prompted once per chat request."""

    def __init__(self, host: Host):
        self._host = host
        self.websocket_connector: Optional[ThreadSafeWebSocketConnector] = (
            host.websocket_connector
        )
        self.current_response: Optional[ChatResponse] = None
        self.available_commands: list[str] = []
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._conn = None
        self._session_id: Optional[str] = None
        self._proc = None
        self._stderr_task = None
        self._started = threading.Event()
        self._start_error: Optional[str] = None
        self._shutdown = None  # asyncio.Event, created on the loop
        self._shutting_down = False
        self._client: Optional[_NbiAcpClient] = None
        self._lock = threading.Lock()
        # Serializes turns: the ACP session runs one prompt at a time, and
        # current_response is shared, so a second concurrent turn must not
        # interleave with the first.
        self._turn_lock = threading.Lock()

    @property
    def codex_settings(self) -> dict:
        return self._host.nbi_config.codex_settings

    def _ensure_started(self) -> bool:
        with self._lock:
            if (
                self._thread is not None
                and self._thread.is_alive()
                and not self._shutting_down
            ):
                return self._start_error is None
            # A thread that is shutting down (or already dead) must not be
            # reused: its loop is closing, so scheduling a prompt on it would
            # hang. Wait for it to exit, then start a fresh one.
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=_START_TIMEOUT)
            self._started.clear()
            self._start_error = None
            self._shutting_down = False
            self._thread = threading.Thread(
                target=self._thread_main, name="nbi-codex-acp", daemon=True
            )
            self._thread.start()
        if not self._started.wait(timeout=_START_TIMEOUT):
            self._start_error = self._start_error or "Codex agent did not start in time"
            return False
        return self._start_error is None

    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except Exception as e:
            self._start_error = f"Codex agent failed to start: {e}"
            log.error(self._start_error, exc_info=True)
            self._started.set()

    async def _serve(self):
        self._loop = asyncio.get_running_loop()
        self._shutdown = asyncio.Event()
        workdir = get_jupyter_root_dir()
        env = self._child_env()
        cmd = resolve_codex_acp_command() + codex_approval_args(
            bool(self.codex_settings.get("full_access", False))
        )
        log.info("Starting codex-acp: %s", " ".join(cmd))
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=workdir, env=env,
            )
            self._stderr_task = asyncio.create_task(self._drain_stderr())
            self._client = _NbiAcpClient(self)
            self._conn = acp.connect_to_agent(
                self._client, self._proc.stdin, self._proc.stdout
            )
            init = await self._conn.initialize(
                protocol_version=acp.PROTOCOL_VERSION,
                client_capabilities=schema.ClientCapabilities(
                    fs=schema.FileSystemCapabilities(read_text_file=True, write_text_file=True),
                ),
                client_info=schema.Implementation(name="notebook-intelligence", version="1.0.0"),
            )
            await self._authenticate(init)
            mcp = schema.McpServerStdio(
                name="nbi", command=sys.executable,
                args=["-m", "notebook_intelligence.acp_mcp_server"], env=[],
            )
            sess = await self._conn.new_session(cwd=workdir, mcp_servers=[mcp])
            self._session_id = sess.session_id
            log.info("codex-acp session ready: %s", self._session_id)
        except Exception as e:
            self._start_error = f"Codex agent session failed: {e}"
            log.error(self._start_error, exc_info=True)
            self._started.set()
            await self._teardown()
            return
        self._started.set()
        try:
            await self._shutdown.wait()
        finally:
            await self._teardown()

    def _child_env(self) -> dict:
        env = {k: v for k, v in os.environ.items()
               if k != "CLAUDECODE" and not k.startswith("CLAUDE_CODE_")}
        api_key = (self.codex_settings.get("api_key") or "").strip() \
            or os.environ.get("OPENAI_API_KEY", "").strip()
        if api_key:
            env["OPENAI_API_KEY"] = api_key
            # Use a clean config dir so a stale ChatGPT OAuth token doesn't
            # shadow API-key auth (the spike hit refresh_token_reused).
            env["CODEX_HOME"] = os.path.join(
                self._host.nbi_config.nbi_user_dir, "codex-home"
            )
            os.makedirs(env["CODEX_HOME"], exist_ok=True)
        return env

    async def _authenticate(self, init):
        methods = [m.id for m in (init.auth_methods or [])]
        if not methods:
            return
        api_key = (self.codex_settings.get("api_key") or "").strip() \
            or os.environ.get("OPENAI_API_KEY", "").strip()
        method = "openai-api-key" if (api_key and "openai-api-key" in methods) else methods[0]
        try:
            await self._conn.authenticate(method_id=method)
        except Exception as e:
            log.warning("codex-acp authenticate(%s) failed: %s", method, e)

    async def _drain_stderr(self):
        while self._proc and self._proc.stderr:
            line = await self._proc.stderr.readline()
            if not line:
                break
            s = line.decode(errors="replace").rstrip()
            if s:
                log.debug("codex-acp: %s", s[:200])

    async def _teardown(self):
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                    await self._proc.wait()
                except Exception:
                    pass
        task = getattr(self, "_stderr_task", None)
        if task is not None:
            task.cancel()
        # Drop references to the dying loop/session so _ensure_started can't
        # hand a closing loop to the next turn (see the restart race).
        self._conn = None
        self._session_id = None
        self._client = None
        self._proc = None
        self._loop = None

    async def _run_prompt(self, text: str):
        await self._conn.prompt(
            prompt=[schema.TextContentBlock(type="text", text=text)],
            session_id=self._session_id,
        )

    async def _cancel(self):
        try:
            if self._conn and self._session_id:
                await self._conn.cancel(session_id=self._session_id)
        except Exception as e:
            log.debug("codex-acp cancel failed: %s", e)

    def query(self, request: ChatRequest, response: ChatResponse) -> Optional[str]:
        """Run one turn. Returns an error string on failure, else None.

        Mirrors ClaudeCodeClient.query: blocks the per-request thread while the
        turn streams on the ACP loop thread.
        """
        if not self._turn_lock.acquire(blocking=False):
            return "Codex agent is busy with another request"
        try:
            if not self._ensure_started():
                return self._start_error or "Codex agent is not available"
            loop = self._loop
            if loop is None:
                return "Codex agent is not available"
            # Fresh turn: drop the prior turn's accumulated tool-call cards so
            # the per-id merge cache does not grow without bound.
            if self._client is not None:
                self._client._tool_state.clear()
            self.current_response = response
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._run_prompt(request.prompt), loop
                )
            except RuntimeError as e:
                return f"Codex agent is not available: {e}"
            start = time.time()
            try:
                while True:
                    if request.cancel_token is not None and request.cancel_token.is_cancel_requested:
                        self._schedule(self._cancel(), loop)
                        return None
                    try:
                        fut.result(timeout=_POLL)
                        return None
                    except concurrent.futures.TimeoutError:
                        pass
                    except Exception as e:
                        log.error("codex-acp turn failed: %s", e, exc_info=True)
                        return f"Codex agent error: {e}"
                    if time.time() - start > _RESPONSE_TIMEOUT:
                        self._schedule(self._cancel(), loop)
                        return "Codex agent response timeout"
            finally:
                self.current_response = None
        finally:
            self._turn_lock.release()

    def _schedule(self, coro, loop):
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()

    def shutdown(self):
        # Mark shutting-down first so a concurrent _ensure_started won't reuse
        # the loop that is about to close.
        self._shutting_down = True
        if self._loop is not None and self._shutdown is not None:
            try:
                self._loop.call_soon_threadsafe(self._shutdown.set)
            except Exception:
                pass


class CodexAgentChatParticipant(BaseChatParticipant):
    def __init__(self, host: Host):
        super().__init__()
        self._host = host
        self._client = AcpAgentClient(host)

    @property
    def id(self) -> str:
        return CODEX_AGENT_CHAT_PARTICIPANT_ID

    @property
    def name(self) -> str:
        return "Codex"

    @property
    def description(self) -> str:
        return "OpenAI Codex (via the Agent Client Protocol)"

    @property
    def icon_path(self) -> str:
        return CODEX_AGENT_ICON_URL

    @property
    def commands(self) -> list[ChatCommand]:
        return [ChatCommand(name=c, description="") for c in self._client.available_commands]

    @property
    def websocket_connector(self) -> ThreadSafeWebSocketConnector:
        return self._client.websocket_connector

    @websocket_connector.setter
    def websocket_connector(self, connector: ThreadSafeWebSocketConnector):
        self._client.websocket_connector = connector

    def restart_client(self) -> None:
        """Stop the running ACP client so the next request restarts it.

        Codex reads its credentials and model from codex_settings at launch; a
        settings change only takes effect on a fresh subprocess.
        """
        self._client.shutdown()

    def chat_prompt(self, model_provider: str, model_name: str) -> str:
        return ""

    async def handle_chat_request(
        self, request: ChatRequest, response: ChatResponse, options: dict = {}
    ) -> None:
        self._current_chat_request = request
        try:
            response.stream(ProgressData("Thinking…"))
            result = self._client.query(request, response)
            if isinstance(result, str) and result:
                response.stream(MarkdownData(content=f"**Codex agent error:** {result}"))
        except Exception as e:
            log.error("Error handling Codex chat request: %s", e, exc_info=True)
            try:
                response.stream(MarkdownData(content=f"**Error:** {e}"))
            except Exception:
                pass
        finally:
            try:
                response.finish()
            except Exception:
                pass
