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

    def test_joined_form_with_language_and_kernel(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '/w' "
            "and current file is: 'nb.ipynb' "
            "and active programming language is: 'python' "
            "with active kernel name: 'python3' (Python 3 (ipykernel)) "
            "What does this cell do?"
        )
        assert _strip_context_preamble(title) == "What does this cell do?"

    def test_codex_title_cut_inside_the_pointer_names_the_file(self):
        # Verbatim session/list title from codex-acp 0.16.0: the pointer
        # fills its 117 characters, so none of the question survives.
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '' "
            "and current file is: 'analysis.py' and active programmin..."
        )
        assert _strip_context_preamble(title) == "analysis.py"

    # The titles below are built from a pointer shaped like extension.py's
    # and truncated the way each agent truncates, so each is one the picker
    # can actually receive.

    def test_codex_title_names_the_file_relative_to_the_directory(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title(_prompt(
            "notebooks", "notebooks/eda.ipynb", "python", "python3",
            "Python 3 (ipykernel)", question="Summarize the data",
        ))
        assert _strip_context_preamble(title) == "eda.ipynb"

    def test_codex_title_cut_inside_the_file_name_shows_the_partial_name(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title(_prompt(
            "reports", "reports/2026-q3-regional-summary.ipynb", "python",
            question="Summarize the data",
        ))
        assert _strip_context_preamble(title) == "2026-q3-regional-su..."

    def test_codex_title_cut_before_the_file_name_names_the_directory(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title(_prompt(
            "projects/analytics", "projects/analytics/revenue.ipynb", "python",
            question="Summarize the data",
        ))
        assert _strip_context_preamble(title) == "projects/analytics"

    def test_codex_title_file_outside_the_directory_keeps_its_path(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title(_prompt(
            "notebooks", "data/load.py", "python", question="Summarize the data",
        ))
        assert _strip_context_preamble(title) == "data/load.py"

    def test_codex_title_file_named_like_the_start_of_the_directory_keeps_its_name(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title(_prompt(
            "notes-archive", "notes", "python", question="Summarize the data",
        ))
        assert _strip_context_preamble(title) == "notes"

    def test_codex_title_cut_before_any_file_names_the_directory(self):
        # No document focused (for example the launcher): the pointer has a
        # directory and a language but no file.
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title(_prompt(
            "notebooks/experiments/2026", language="python",
            question="Summarize the data",
        ))
        assert _strip_context_preamble(title) == "notebooks/experiments/2026"

    def test_codex_title_cut_inside_the_file_label_names_the_directory(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title(_prompt(
            "home/analyst/projects/2026/quarterly",
            "home/analyst/projects/2026/quarterly/a.ipynb", "python", "python3",
            "Python 3 (ipykernel)", question="Summarize the data",
        ))
        assert _strip_context_preamble(title) == "home/analyst/projects/2026/quarterly"

    def test_codex_title_cut_inside_the_kernel_label_with_no_directory_is_empty(self):
        # Notebook generation sends no file and an empty directory.
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title(_prompt(
            "", language="python", kernel="python3", display="Python 3 (ipykernel)",
            question="Create a notebook that plots revenue",
        ))
        assert _strip_context_preamble(title) == ""

    def test_codex_title_cut_inside_the_directory_is_empty(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title(_prompt(
            "home/analyst/projects/2026/quarterly-revenue-review/regional",
            "home/analyst/projects/2026/quarterly-revenue-review/regional/a.ipynb",
            "python", question="Summarize the data",
        ))
        assert _strip_context_preamble(title) == ""

    def test_codex_title_keeps_a_truncated_question(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title(_prompt(
            "", language="python",
            question="Run analysis.py and check whether the revenue totals "
            "look right, then fix anything that is wrong",
        ))
        assert _strip_context_preamble(title) == "Run analysi..."

    def test_claude_code_acp_title_names_the_file(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _claude_code_acp_title(_prompt(
            "", "analysis.ipynb", "python", "python3", "Python 3 (ipykernel)",
            question="Summarize the data",
        ))
        assert _strip_context_preamble(title) == "analysis.ipynb"

    def test_claude_code_acp_title_cut_inside_the_file_name(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _claude_code_acp_title(_prompt(
            "", "quarterly-revenue-review-by-region-and-product-line.ipynb",
            "python", question="Summarize the data",
        ))
        assert _strip_context_preamble(title) == (
            "quarterly-revenue-review-by-region-and-produ\u2026"
        )

    def test_hoisted_slash_command_before_the_pointer_is_kept(self):
        # assemble_query moves a custom command in front of the context lines.
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = _codex_title("/analyze\n" + _prompt(
            "", "analysis.py", "python", question="",
        ))
        assert _strip_context_preamble(title) == "/analyze"

    # Shapes the agents do not produce, pinning the matcher on its own.

    def test_cut_inside_a_quoted_value_names_the_file(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '/w' "
            "and current file is: 'nb.ipynb' "
            "and active programming language is: 'pyt..."
        )
        assert _strip_context_preamble(title) == "nb.ipynb"

    def test_cut_at_a_segment_boundary_names_the_file(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '/w' "
            "and current file is: 'nb.ipynb'..."
        )
        assert _strip_context_preamble(title) == "nb.ipynb"

    def test_cut_inside_the_kernel_display_name_names_the_file(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '' "
            "and current file is: 'a.ipynb' "
            "with active kernel name: 'python3' (Python 3 (ipyk..."
        )
        assert _strip_context_preamble(title) == "a.ipynb"

    def test_question_ending_in_an_ellipsis_is_not_mistaken_for_a_cut(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '' "
            "and current file is: 'a.py' Wait for it..."
        )
        assert _strip_context_preamble(title) == "Wait for it..."

    def test_segment_text_without_a_marker_is_the_question(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = "Additional context: Current directory open in Jupyter is: '' with"
        assert _strip_context_preamble(title) == "with"

    def test_parenthesized_question_without_a_kernel_is_kept(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '' "
            "and current file is: 'a.py' (quick one) what does line 3 do?"
        )
        assert _strip_context_preamble(title) == "(quick one) what does line 3 do?"

    def test_truncated_parenthesized_question_without_a_kernel_is_kept(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '' "
            "and current file is: 'a.py' (quick one about the loop in..."
        )
        assert _strip_context_preamble(title) == "(quick one about the loop in..."

    def test_truncated_parenthesized_question_after_a_display_name_is_kept(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '/w' "
            "and current file is: 'nb.ipynb' "
            "and active programming language is: 'python' "
            "with active kernel name: 'python3' (Python 3 (ipykernel)) "
            "(quick one about the loop in..."
        )
        assert _strip_context_preamble(title) == "(quick one about the loop in..."

    def test_untruncated_pointer_with_no_question_names_the_file(self):
        from notebook_intelligence.acp_agent import _strip_context_preamble
        title = (
            "Additional context: Current directory open in Jupyter is: '/w' "
            "and current file is: 'nb.ipynb'"
        )
        assert _strip_context_preamble(title) == "nb.ipynb"


def _prompt(directory, file="", language="", kernel="", display="", question=""):
    """A first prompt shaped like extension.py's: the pointer, then the question."""
    from notebook_intelligence.claude_sessions import NBI_CONTEXT_PREFIX
    pointer = f"{NBI_CONTEXT_PREFIX} '{directory}'"
    if file:
        pointer += f" and current file is: '{file}'"
    if language:
        pointer += f" and active programming language is: '{language}'"
    if kernel:
        pointer += f" with active kernel name: '{kernel}'"
    if display:
        pointer += f" ({display})"
    return f"{pointer}\n{question}" if question else pointer


def _codex_title(prompt):
    """codex-acp's session title for ASCII text (it counts graphemes): newlines
    as spaces, 117 characters plus "..."."""
    text = prompt.replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= 120 else text[:117] + "..."


def _claude_code_acp_title(prompt):
    """claude-code-acp's sanitizeTitle for ASCII text (it counts UTF-16 units):
    whitespace collapsed, 127 characters plus U+2026."""
    text = " ".join(prompt.split())
    return text if len(text) <= 128 else text[:127] + "\u2026"


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
