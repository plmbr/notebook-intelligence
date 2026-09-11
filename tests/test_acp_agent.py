# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Unit tests for the ACP backend mapping (issue #378, Phase 1).

These exercise the editor-side translation (ACP events -> NBI cards/approval)
without launching codex-acp; the live end-to-end path is covered by the
Phase 0 spike and the JupyterLab Playwright check.
"""

import asyncio
import concurrent.futures
from types import SimpleNamespace

import pytest

import acp
from acp import schema

from notebook_intelligence.acp_agent import (
    _NbiAcpClient,
    _diffs_from_content,
    _nbi_kind,
    _nbi_status,
)
from notebook_intelligence.api import ChatResponse, ResponseStreamDataType


class FakeResponse(ChatResponse):
    """Captures streamed data and supports the user-input signal round trip."""

    def __init__(self):
        super().__init__()
        self.streamed = []

    @property
    def message_id(self) -> str:
        return "msg-1"

    def stream(self, data, finish: bool = False) -> None:
        self.streamed.append(data)

    def finish(self) -> None:
        pass


def _client_with_response(resp):
    owner = SimpleNamespace(
        current_response=resp,
        agent_spec=SimpleNamespace(label="Codex"),
    )
    return _NbiAcpClient(owner)


class TestKindStatusMapping:
    @pytest.mark.parametrize("acp_kind,expected", [
        ("read", "read"), ("search", "read"), ("fetch", "read"),
        ("edit", "edit"), ("delete", "edit"), ("move", "edit"),
        ("execute", "execute"), ("think", "other"), (None, "other"),
    ])
    def test_kind(self, acp_kind, expected):
        assert _nbi_kind(acp_kind) == expected

    @pytest.mark.parametrize("acp_status,expected", [
        ("pending", "in_progress"), ("in_progress", "in_progress"),
        (None, "in_progress"), ("completed", "completed"), ("failed", "failed"),
    ])
    def test_status(self, acp_status, expected):
        assert _nbi_status(acp_status) == expected


class TestDiffMapping:
    def test_file_edit_content_becomes_typed_diff_lines(self):
        content = [SimpleNamespace(type="diff", path="/x.py", old_text="a\n", new_text="a\nb\n")]
        diffs = _diffs_from_content(content)
        assert len(diffs) == 1
        assert diffs[0]["path"] == "/x.py"
        assert {"type": "add", "content": "b"} in diffs[0]["lines"]

    def test_non_diff_content_ignored(self):
        content = [SimpleNamespace(type="content", text="hello")]
        assert _diffs_from_content(content) == []


class TestToolCallStreaming:
    def test_tool_call_emits_card_with_kind_and_diff(self):
        resp = FakeResponse()
        client = _client_with_response(resp)
        update = SimpleNamespace(
            session_update="tool_call", tool_call_id="t1", kind="edit",
            status="in_progress", title="Edit /x.py",
            content=[SimpleNamespace(type="diff", path="/x.py", old_text="", new_text="hi\n")],
        )
        asyncio.run(client.session_update("s", update))
        cards = [d for d in resp.streamed if d.data_type == ResponseStreamDataType.ToolCall]
        assert len(cards) == 1
        assert cards[0].id == "t1" and cards[0].kind == "edit"
        assert cards[0].status == "in_progress" and cards[0].diffs

    def test_partial_update_merges_cached_kind(self):
        resp = FakeResponse()
        client = _client_with_response(resp)
        asyncio.run(client.session_update("s", SimpleNamespace(
            session_update="tool_call", tool_call_id="t1", kind="execute",
            status="in_progress", title="Run", content=None)))
        # A later update carries only the new status; kind must survive.
        asyncio.run(client.session_update("s", SimpleNamespace(
            session_update="tool_call_update", tool_call_id="t1", kind=None,
            status="completed", title=None, content=None)))
        last = [d for d in resp.streamed if d.data_type == ResponseStreamDataType.ToolCall][-1]
        assert last.kind == "execute" and last.status == "completed"

    def test_agent_message_chunk_streams_markdown_part(self):
        # MarkdownPart, not Markdown: ACP delivers token-sized deltas and the
        # frontend only concatenates consecutive *parts* into one block. With
        # Markdown every delta rendered as its own paragraph (the one-word-
        # per-line bug from the PR #380 review).
        resp = FakeResponse()
        client = _client_with_response(resp)
        asyncio.run(client.session_update("s", SimpleNamespace(
            session_update="agent_message_chunk",
            content=SimpleNamespace(text="hello world"))))
        md = [d for d in resp.streamed if d.data_type == ResponseStreamDataType.MarkdownPart]
        assert md and md[0].content == "hello world"

    def test_agent_thought_chunk_streams_reasoning_part(self):
        resp = FakeResponse()
        client = _client_with_response(resp)
        asyncio.run(client.session_update("s", SimpleNamespace(
            session_update="agent_thought_chunk",
            content=SimpleNamespace(text="mulling"))))
        md = [d for d in resp.streamed if d.data_type == ResponseStreamDataType.MarkdownPart]
        assert md and md[0].reasoning_content == "mulling"


class TestPermission:
    def _opts(self):
        return [
            schema.PermissionOption(kind="allow_once", name="Allow", option_id="a1"),
            schema.PermissionOption(kind="reject_once", name="Reject", option_id="r1"),
        ]

    def _tool_call(self):
        return SimpleNamespace(tool_call_id="t1", title="Run echo")

    def _run_with_answer(self, confirmed):
        resp = FakeResponse()
        client = _client_with_response(resp)

        async def drive():
            task = asyncio.create_task(
                client.request_permission(self._opts(), "s", self._tool_call())
            )
            # Let request_permission stream the card and start awaiting input.
            await asyncio.sleep(0.05)
            assert any(
                d.data_type == ResponseStreamDataType.Confirmation for d in resp.streamed
            )
            resp.on_user_input({
                "callback_id": "acp-perm-t1", "data": {"confirmed": confirmed}
            })
            return await task

        return asyncio.run(drive())

    def test_approve_selects_allow_option(self):
        result = self._run_with_answer(True)
        assert isinstance(result.outcome, schema.AllowedOutcome)
        assert result.outcome.option_id == "a1"

    def test_reject_selects_reject_option(self):
        result = self._run_with_answer(False)
        assert isinstance(result.outcome, schema.AllowedOutcome)
        assert result.outcome.option_id == "r1"

    def test_no_response_fails_closed(self):
        client = _client_with_response(None)
        result = asyncio.run(
            client.request_permission(self._opts(), "s", self._tool_call())
        )
        assert isinstance(result.outcome, schema.DeniedOutcome)


class TestPolicyClamp:
    def test_force_off_clamps_enabled(self):
        from notebook_intelligence.feature_flags import apply_acp_policies
        assert apply_acp_policies({"enabled": True}, {"acp_mode": "force-off"}) == {"enabled": False}

    def test_user_choice_keeps_user_value(self):
        from notebook_intelligence.feature_flags import apply_acp_policies
        assert apply_acp_policies({"enabled": True}, {"acp_mode": "user-choice"}) == {"enabled": True}

    def test_full_access_force_off_clamps(self):
        from notebook_intelligence.feature_flags import apply_acp_policies
        out = apply_acp_policies(
            {"full_access": True}, {"acp_full_access": "force-off"}
        )
        assert out["full_access"] is False

    def test_full_access_user_choice_keeps_value(self):
        from notebook_intelligence.feature_flags import apply_acp_policies
        assert (
            apply_acp_policies(
                {"full_access": True}, {"acp_full_access": "user-choice"}
            )["full_access"]
            is True
        )

    def test_full_access_force_on(self):
        from notebook_intelligence.feature_flags import apply_acp_policies
        assert (
            apply_acp_policies(
                {"full_access": False}, {"acp_full_access": "force-on"}
            )["full_access"]
            is True
        )


class TestApprovalArgs:
    """The approval posture pinned onto the codex-acp command line."""

    def test_default_pins_untrusted(self):
        from notebook_intelligence.acp_agent import codex_approval_args
        args = codex_approval_args(False)
        assert args == ["-c", 'approval_policy="untrusted"']

    def test_full_access_runs_unattended(self):
        from notebook_intelligence.acp_agent import codex_approval_args
        assert codex_approval_args(True) == ["-c", 'approval_policy="never"']


class TestCodexModelArgs:
    """Model and base-URL settings pinned onto the codex-acp command line.

    Codex ignores the OPENAI_BASE_URL env var, so the -c openai_base_url
    override is the only path that gets a custom endpoint to the agent
    (the PR #380 regression: a proxy user's key was sent to api.openai.com
    and 401ed).
    """

    def test_empty_settings_add_nothing(self):
        from notebook_intelligence.acp_registry import codex_model_args
        assert codex_model_args({}) == []
        assert codex_model_args({"chat_model": "", "base_url": "  "}) == []

    def test_base_url_becomes_openai_base_url_override(self):
        from notebook_intelligence.acp_registry import codex_model_args
        args = codex_model_args({"base_url": "http://127.0.0.1:8901/v1"})
        assert args == ["-c", 'openai_base_url="http://127.0.0.1:8901/v1"']

    def test_chat_model_becomes_model_override(self):
        from notebook_intelligence.acp_registry import codex_model_args
        assert codex_model_args({"chat_model": "gpt-5.2-codex"}) == [
            "-c", 'model="gpt-5.2-codex"'
        ]

    def test_both_settings_yield_both_overrides(self):
        from notebook_intelligence.acp_registry import codex_model_args
        args = codex_model_args(
            {"chat_model": "gpt-5.2-codex", "base_url": "https://llm.corp/v1"}
        )
        assert args == [
            "-c", 'model="gpt-5.2-codex"',
            "-c", 'openai_base_url="https://llm.corp/v1"',
        ]

    def test_values_are_quoted_as_toml_strings(self):
        from notebook_intelligence.acp_registry import codex_model_args
        args = codex_model_args({"base_url": 'https://x/v1?a="b"\\c'})
        assert args == ["-c", 'openai_base_url="https://x/v1?a=\\"b\\"\\\\c"']

    def test_control_chars_are_dropped(self):
        """Control chars cannot ride in a TOML basic string; an interior
        newline from a paste artifact must not break the codex launch."""
        from notebook_intelligence.acp_registry import codex_model_args
        args = codex_model_args({"base_url": "https://proxy\n.corp/v1\x01"})
        assert args == ["-c", 'openai_base_url="https://proxy.corp/v1"']

    def test_value_left_empty_by_cleaning_adds_no_flag(self):
        """An empty override is not neutral: it would blank out the model
        codex would otherwise take from its config file or default."""
        from notebook_intelligence.acp_registry import codex_model_args
        assert codex_model_args({"chat_model": "\x08", "base_url": "\x01\x02"}) == []

    def test_serve_appends_overrides_to_launch_cmd(self, tmp_path):
        """Pin the delivery, not just the mapping: the original bug was
        settings that never reached the launch command at all."""
        import notebook_intelligence.acp_agent as mod

        host = SimpleNamespace(
            websocket_connector=None,
            nbi_config=SimpleNamespace(
                acp_settings={
                    "enabled": True, "agent": "codex",
                    "chat_model": "m1", "base_url": "http://proxy/v1",
                    "full_access": False,
                },
                nbi_user_dir=str(tmp_path),
            ),
        )
        client = mod.AcpAgentClient(host)
        captured = {}

        async def fake_exec(*cmd, **kw):
            captured["cmd"] = list(cmd)
            raise RuntimeError("captured; abort launch")

        orig = mod.asyncio.create_subprocess_exec
        mod.asyncio.create_subprocess_exec = fake_exec
        try:
            asyncio.run(client._serve())
        finally:
            mod.asyncio.create_subprocess_exec = orig

        assert captured["cmd"][-6:] == [
            "-c", 'approval_policy="untrusted"',
            "-c", 'model="m1"',
            "-c", 'openai_base_url="http://proxy/v1"',
        ]


class TestClientFileSystemNotOffered:
    """NBI does not serve ``fs/read_text_file`` or ``fs/write_text_file``.

    They would run in the Jupyter server process, outside any agent sandbox,
    so a delegating agent could reach any path the server can. The acp router
    registers the handlers regardless of the advertised capability, so the
    advertisement, the handlers, and the router's answer are all pinned."""

    @staticmethod
    def _snapshot(root):
        return {p: (p.read_bytes() if p.is_file() else None) for p in root.rglob("*")}

    @pytest.mark.parametrize("layout", ["missing_parent", "existing_parent", "existing_file"])
    def test_write_is_refused_and_leaves_the_disk_unchanged(self, tmp_path, layout):
        (tmp_path / "existing").mkdir()
        if layout == "missing_parent":
            target = tmp_path / "new" / "planted.txt"
        elif layout == "existing_parent":
            target = tmp_path / "existing" / "planted.txt"
        else:
            target = tmp_path / "existing" / "kept.txt"
            target.write_text("ORIGINAL", encoding="utf-8")
        before = self._snapshot(tmp_path)

        with pytest.raises(acp.RequestError) as excinfo:
            asyncio.run(_client_with_response(None).write_text_file(
                content="planted", path=str(target), session_id="s",
            ))

        assert excinfo.value.to_error_obj()["code"] == -32601
        assert self._snapshot(tmp_path) == before

    def test_read_is_refused_without_returning_the_file(self, tmp_path):
        target = tmp_path / "notes.txt"
        target.write_text("SECRET-CONTENT-7F3A", encoding="utf-8")

        with pytest.raises(acp.RequestError) as excinfo:
            asyncio.run(_client_with_response(None).read_text_file(
                path=str(target), session_id="s",
            ))

        error = excinfo.value.to_error_obj()
        assert error["code"] == -32601
        assert "SECRET-CONTENT-7F3A" not in repr(error)

    @pytest.mark.parametrize("method,params", [
        ("fs/read_text_file", {"sessionId": "s", "line": 1, "limit": 5}),
        ("fs/write_text_file", {"sessionId": "s", "content": "planted"}),
        ("_nbi/unknown", {}),
    ])
    def test_router_answers_method_not_found(self, tmp_path, method, params):
        """Pin the answer at the protocol boundary, where the router maps
        request params onto the handler's arguments."""
        from acp.client.router import build_client_router

        target = tmp_path / "planted.txt"
        if method.startswith("fs/"):
            params = {**params, "path": str(target)}
        router = build_client_router(_client_with_response(None))

        with pytest.raises(acp.RequestError) as excinfo:
            asyncio.run(router(method, params, False))

        assert excinfo.value.to_error_obj()["code"] == -32601
        assert not target.exists()

    def test_initialize_does_not_advertise_fs(self, tmp_path, monkeypatch):
        import inspect

        from acp.client.connection import ClientSideConnection

        import notebook_intelligence.acp_agent as mod

        # A missed patch must fail fast rather than launch a real agent.
        monkeypatch.setenv("NBI_ACP_AGENT_COMMAND", "nbi-test-must-not-spawn")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        captured = {}

        class FakeProc:
            stdin = stdout = object()
            stderr = None
            returncode = None

            def terminate(self):
                self.returncode = 0

            async def wait(self):
                return 0

        async def fake_exec(*cmd, **kw):
            return FakeProc()

        class FakeConn:
            async def initialize(self, *args, **kwargs):
                bound = inspect.signature(ClientSideConnection.initialize).bind(
                    self, *args, **kwargs
                )
                captured["capabilities"] = (
                    bound.arguments.get("client_capabilities")
                    or schema.ClientCapabilities()
                )
                raise RuntimeError("test: capabilities captured, session not started")

        monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(mod.acp, "connect_to_agent", lambda *a, **k: FakeConn())
        client = mod.AcpAgentClient(SimpleNamespace(
            websocket_connector=None,
            nbi_config=SimpleNamespace(
                acp_settings={"enabled": True, "agent": "codex"},
                nbi_user_dir=str(tmp_path),
            ),
        ))

        asyncio.run(client._serve())

        assert "capabilities" in captured, (
            f"_serve never reached initialize: {client._start_error}"
        )
        fs = captured["capabilities"].fs
        assert fs.read_text_file is False
        assert fs.write_text_file is False


class TestAssembleQuery:
    """The turn's context lines (attachments, current-file pointer, output
    context) ride along with the prompt — sending only ``request.prompt``
    silently dropped whatever the user had just attached (the file-as-context
    bug from the PR #380 review)."""

    def _assemble(self, chat_history, prompt="the prompt"):
        from notebook_intelligence.acp_agent import AcpAgentClient
        return AcpAgentClient.assemble_query(
            SimpleNamespace(prompt=prompt, chat_history=chat_history)
        )

    def test_context_lines_precede_the_prompt(self):
        query = self._assemble([
            {"role": "user", "content": "The user attached @data.csv."},
            {"role": "user", "content": "what is in this file?"},
        ])
        assert query == "The user attached @data.csv.\nwhat is in this file?"

    def test_empty_history_falls_back_to_prompt(self):
        assert self._assemble([]) == "the prompt"

    def test_non_user_and_non_string_content_skipped(self):
        query = self._assemble([
            {"role": "assistant", "content": "earlier answer"},
            {"role": "user", "content": [{"type": "text", "text": "structured"}]},
            {"role": "user", "content": "the prompt"},
        ])
        assert query == "the prompt"

    def test_control_slash_command_drops_context(self):
        # Context lines are meaningless to a control command and could break
        # its parsing; mirrors the Claude-mode join after #388.
        query = self._assemble([
            {"role": "user", "content": "The user attached @data.csv."},
            {"role": "user", "content": "/compact"},
        ])
        assert query == "/compact"

    def test_custom_slash_command_keeps_context_after_the_command(self):
        # A non-control command is hoisted to the front (the agent only
        # recognizes a command at the start of the prompt) with the turn's
        # context preserved as its arguments; mirrors Claude mode's #388 join.
        query = self._assemble([
            {"role": "user", "content": "The user attached @data.csv."},
            {"role": "user", "content": "/analyze"},
        ])
        assert query == "/analyze\nThe user attached @data.csv."

    def test_bare_custom_command_with_no_context_stays_clean(self):
        query = self._assemble(
            [{"role": "user", "content": "/analyze"}], prompt="/analyze"
        )
        assert query == "/analyze"


class TestStripContextPreamble:
    """Session previews should show the user's first question, not the NBI
    context lines the agent stored as part of its session title."""

    def test_strips_leading_context_lines(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '/w'\n"
            "The user attached @facts.md. Read it if relevant.\n"
            "What is the launch codename?"
        )
        assert _strip_context_preamble(title) == "What is the launch codename?"

    def test_plain_title_unchanged(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        assert _strip_context_preamble("say hi") == "say hi"

    def test_all_context_falls_back_to_original(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = "Additional context: Current directory open in Jupyter is: '/w'"
        assert _strip_context_preamble(title) == title

    def test_joined_form_strips_directory_pointer(self):
        # codex stores titles with newlines collapsed to spaces (and
        # truncated), so the pointer must be peeled off structurally.
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '' "
            "Reply with two short sentences."
        )
        assert _strip_context_preamble(title) == "Reply with two short sentences."

    def test_joined_form_with_current_file(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '/w' "
            "and current file is: 'nb.ipynb' What does this cell do?"
        )
        assert _strip_context_preamble(title) == "What does this cell do?"


class TestSingleFlight:
    """The ACP session runs one prompt at a time; a second concurrent turn
    must be rejected rather than interleave with the first."""

    def _client(self):
        from notebook_intelligence.acp_agent import AcpAgentClient
        host = SimpleNamespace(
            websocket_connector=None,
            nbi_config=SimpleNamespace(acp_settings={"enabled": True}),
        )
        return AcpAgentClient(host)

    def test_second_concurrent_turn_is_rejected(self):
        client = self._client()
        # Simulate a turn already in flight by holding the turn lock.
        assert client._turn_lock.acquire(blocking=False)
        try:
            req = SimpleNamespace(prompt="hi", cancel_token=None, chat_history=[])
            result = client.query(req, FakeResponse())
            assert result is not None and "busy" in result.lower()
        finally:
            client._turn_lock.release()

    def test_unavailable_agent_releases_the_lock(self):
        client = self._client()
        # When the agent can't start, query returns the error and still frees
        # the lock (the outer finally).
        client._ensure_started = lambda: False
        client._start_error = "boom"
        result = client.query(SimpleNamespace(prompt="x", cancel_token=None, chat_history=[]), FakeResponse())
        assert result == "boom"
        assert client._turn_lock.acquire(blocking=False)
        client._turn_lock.release()

    def test_completed_turn_releases_lock_and_resets_tool_state(self):
        client = self._client()
        # Drive query through the inner run/poll body to a clean finish so the
        # nested try/finally (lock release + current_response reset) is covered,
        # not just the early-return path.
        client._ensure_started = lambda: True
        client._loop = object()  # only used as an opaque handle below
        client._client = SimpleNamespace(
            _tool_state={"stale": {}}, _tool_perf_spans={}
        )

        done = concurrent.futures.Future()
        done.set_result(None)

        async def _noop():
            return None

        client._run_prompt = lambda prompt: _noop()

        def fake_schedule(coro, loop):
            coro.close()  # we never run the real prompt coroutine
            return done

        import notebook_intelligence.acp_agent as mod
        orig = mod.asyncio.run_coroutine_threadsafe
        mod.asyncio.run_coroutine_threadsafe = fake_schedule
        try:
            result = client.query(
                SimpleNamespace(prompt="hi", cancel_token=None, chat_history=[]),
                FakeResponse(),
            )
        finally:
            mod.asyncio.run_coroutine_threadsafe = orig

        assert result is None
        # Prior turn's tool-call cache was cleared, lock released, response reset.
        assert client._client._tool_state == {}
        assert client.current_response is None
        assert client._turn_lock.acquire(blocking=False)
        client._turn_lock.release()
