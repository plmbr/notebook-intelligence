"""Scope tests for the Claude-mode UI-bridge tools.

The two MCP tools registered in ``claude.py`` (``run-command-in-jupyter-terminal``
and ``open-file-in-jupyter-ui``) forward their path arguments to JupyterLab
UI commands (``terminal:create-new`` via ``notebook-intelligence:run-command-in-terminal``
and ``docmanager:open``). Before this fix the values were passed straight
through unsanitized: an LLM tool call with ``working_directory='/etc'`` or
``file_path='../../../etc/passwd'`` would land the bridge outside
``jupyter_root_dir``. The sibling ``built_in_toolsets`` tools (covered by
``test_builtin_toolset_cwd_sandbox.py``) already had the gate; this file
mirrors that coverage for the Claude-mode siblings.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

import notebook_intelligence.claude as claude_mod
from notebook_intelligence import util as util_mod


@pytest.fixture
def jupyter_root(tmp_path, monkeypatch):
    # Workspace lives under tmp_path so the parent remains available as an
    # "outside the workspace" target for symlink + absolute-path tests.
    # `monkeypatch.setattr` resets to the prior value on teardown even if
    # the test raises, so state can't leak across tests; matches the
    # sibling pattern in test_builtin_toolset_cwd_sandbox.py.
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(util_mod, "_jupyter_root_dir", str(root))
    return root


@pytest.fixture
def response_spy(monkeypatch):
    # The tool calls `claude.get_current_response().run_ui_command(...)`.
    # Inject a spy so each test can observe whether the UI command was
    # invoked at all, and with what payload when it was. monkeypatch
    # restores _current_response on teardown even if the test raises.
    response = MagicMock()

    async def fake_run_ui_command(cmd, payload):
        return "ok"

    response.run_ui_command.side_effect = fake_run_ui_command
    monkeypatch.setattr(claude_mod, "_current_response", response)
    return response


def _invoke_run_command(working_directory: str, command: str = "echo hi"):
    """Drive run-command-in-jupyter-terminal. Returns the tool's response
    dict so the test can read the text the LLM would see, plus the
    response spy so it can assert the UI command (didn't) fire.
    """
    handler = claude_mod.run_command_in_jupyter_terminal.handler
    result = asyncio.run(
        handler({"command": command, "working_directory": working_directory})
    )
    return result, claude_mod.get_current_response().run_ui_command


def _invoke_open_file(file_path: str):
    handler = claude_mod.open_file_in_jupyter_ui.handler
    result = asyncio.run(handler({"file_path": file_path}))
    return result, claude_mod.get_current_response().run_ui_command


def _text(result) -> str:
    """Extract the text block from a tool_text_response payload."""
    return result["content"][0]["text"]


class TestRunCommandInJupyterTerminalSandbox:
    """The Claude-mode sibling of built_in_toolsets.run_command_in_jupyter_terminal.
    Same security property: the cwd forwarded to the JupyterLab UI command
    must resolve inside jupyter_root_dir, regardless of what the LLM
    supplies.
    """

    def test_rejects_absolute_path_outside_jupyter_root(
        self, jupyter_root, response_spy
    ):
        result, ui_spy = _invoke_run_command("/etc")
        assert "outside allowed directory" in _text(result)
        ui_spy.assert_not_called()

    def test_rejects_relative_traversal_outside_jupyter_root(
        self, jupyter_root, response_spy
    ):
        result, ui_spy = _invoke_run_command("../../..")
        assert "outside allowed directory" in _text(result)
        ui_spy.assert_not_called()

    def test_rejects_workspace_symlink_pointing_outside(
        self, jupyter_root, response_spy, tmp_path
    ):
        # A symlink inside the workspace pointing to /etc would let the LLM
        # escape via Path.resolve() chasing it. Pin that resolve() is
        # called before the relative_to() containment check.
        outside = tmp_path / "outside"
        outside.mkdir()
        link = jupyter_root / "escape"
        link.symlink_to(outside, target_is_directory=True)
        result, ui_spy = _invoke_run_command("escape")
        assert "outside allowed directory" in _text(result)
        ui_spy.assert_not_called()

    def test_rejects_traversal_via_valid_subdir_prefix(
        self, jupyter_root, response_spy
    ):
        # `valid/../../..` resolves above the root even though the literal
        # prefix is a real subdir. Pins that resolve() collapses `..`
        # before the containment check.
        (jupyter_root / "valid").mkdir()
        result, ui_spy = _invoke_run_command("valid/../../..")
        assert "outside allowed directory" in _text(result)
        ui_spy.assert_not_called()

    def test_rejects_null_byte_in_path(self, jupyter_root, response_spy):
        # pathlib raises ValueError on embedded NUL bytes. The fix's
        # try/except converts that to a tool-result error string without
        # forwarding to the UI command. Pin so a future refactor that
        # swallows the exception cannot reopen the hole.
        result, ui_spy = _invoke_run_command("evil\x00")
        # Either the explicit "outside" branch (after pathlib normalizes)
        # or the pathlib-raised ValueError → "Error: ..." string. The
        # load-bearing assertion is that the UI bridge never fired.
        ui_spy.assert_not_called()
        assert isinstance(_text(result), str)

    def test_rejects_nonexistent_directory(self, jupyter_root, response_spy):
        result, ui_spy = _invoke_run_command("does-not-exist")
        assert "does not exist" in _text(result)
        ui_spy.assert_not_called()

    def test_rejects_path_that_is_a_file_not_a_directory(
        self, jupyter_root, response_spy
    ):
        f = jupyter_root / "note.txt"
        f.write_text("hi")
        result, ui_spy = _invoke_run_command("note.txt")
        assert "not a directory" in _text(result)
        ui_spy.assert_not_called()

    def test_allows_relative_subdirectory(self, jupyter_root, response_spy):
        sub = jupyter_root / "work"
        sub.mkdir()
        result, ui_spy = _invoke_run_command("work")
        assert ui_spy.call_count == 1
        payload = ui_spy.call_args.args[1]
        # cwd is the sandboxed absolute path, not the LLM-supplied
        # relative value. Belt-and-suspenders: the JupyterLab command
        # gets a fully-resolved path so a future intermediate that does
        # its own cwd-relative resolution can't double-resolve.
        assert payload["cwd"] == str(sub.resolve())
        # Command is forwarded verbatim.
        assert payload["command"] == "echo hi"

    def test_dot_means_jupyter_root(self, jupyter_root, response_spy):
        result, ui_spy = _invoke_run_command(".")
        assert ui_spy.call_count == 1
        payload = ui_spy.call_args.args[1]
        assert payload["cwd"] == str(jupyter_root.resolve())

    def test_empty_string_means_jupyter_root(self, jupyter_root, response_spy):
        # The schema doc says "default is '' which translates to the
        # Jupyter working directory root". safe_jupyter_path treats an
        # empty path as the root via the relative-join branch. Pin so a
        # future ``if not working_directory: ...`` short-circuit can't
        # bypass the gate by feeding `""` straight through.
        result, ui_spy = _invoke_run_command("")
        assert ui_spy.call_count == 1
        payload = ui_spy.call_args.args[1]
        assert payload["cwd"] == str(jupyter_root.resolve())


class TestOpenFileInJupyterUiSandbox:
    """The open-file tool routes through ``docmanager:open``, which today
    rejects out-of-root absolute paths via JupyterLab's contents service.
    Re-applying the same containment check server-side keeps the security
    posture from depending on a framework behavior, and gives the LLM the
    same error wording the other path-bearing tools use instead of a
    JupyterLab-internal 404 string.
    """

    def test_rejects_absolute_path_outside_jupyter_root(
        self, jupyter_root, response_spy
    ):
        result, ui_spy = _invoke_open_file("/etc/passwd")
        assert "outside allowed directory" in _text(result)
        ui_spy.assert_not_called()

    def test_rejects_relative_traversal_outside_jupyter_root(
        self, jupyter_root, response_spy
    ):
        result, ui_spy = _invoke_open_file("../../etc/passwd")
        assert "outside allowed directory" in _text(result)
        ui_spy.assert_not_called()

    def test_rejects_workspace_symlink_pointing_outside(
        self, jupyter_root, response_spy, tmp_path
    ):
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        link = jupyter_root / "escape.txt"
        link.symlink_to(outside)
        result, ui_spy = _invoke_open_file("escape.txt")
        assert "outside allowed directory" in _text(result)
        ui_spy.assert_not_called()

    def test_rejects_null_byte_in_path(self, jupyter_root, response_spy):
        result, ui_spy = _invoke_open_file("foo\x00.txt")
        ui_spy.assert_not_called()
        assert isinstance(_text(result), str)

    def test_allows_relative_file_inside_root(self, jupyter_root, response_spy):
        # Existence isn't a server-side concern here (docmanager:open will
        # surface a missing-file error in its own UX). The security gate
        # only verifies containment.
        (jupyter_root / "notebook.ipynb").write_text("{}")
        result, ui_spy = _invoke_open_file("notebook.ipynb")
        assert ui_spy.call_count == 1
        payload = ui_spy.call_args.args[1]
        # `docmanager:open` routes its `path` through
        # JupyterLab's contents service, which strips the leading slash
        # and rejoins under root_dir (jupyter_server.utils.to_os_path).
        # Forwarding an absolute path would 404 the file. The sandbox
        # forwards the *relative-to-root* form so the lookup succeeds.
        assert payload["path"] == "notebook.ipynb"

    def test_allows_file_that_does_not_exist_yet(
        self, jupyter_root, response_spy
    ):
        # docmanager:open is also used to open files about to be created.
        # The security gate must not require existence (that's a UX
        # concern, surfaced by docmanager).
        result, ui_spy = _invoke_open_file("brand-new.ipynb")
        assert ui_spy.call_count == 1
        payload = ui_spy.call_args.args[1]
        assert payload["path"] == "brand-new.ipynb"

    def test_allows_nested_path_relative_to_root(
        self, jupyter_root, response_spy
    ):
        # A deeper path inside the workspace forwards as the relative
        # POSIX form, not the absolute one.
        sub = jupyter_root / "notebooks" / "experiments"
        sub.mkdir(parents=True)
        result, ui_spy = _invoke_open_file("notebooks/experiments/exp1.ipynb")
        assert ui_spy.call_count == 1
        payload = ui_spy.call_args.args[1]
        assert payload["path"] == "notebooks/experiments/exp1.ipynb"


class TestMCPErrorSignalling:
    """Pin that rejection paths set the MCP ``is_error`` flag. Without
    this, the Claude Agent SDK treats the rejection text as a successful
    tool result and model-side retry heuristics can't tell sandbox
    violations apart from authoritative output. The flag is read at
    ``claude_agent_sdk/__init__.py``: ``result.get("is_error", False)``
    → ``CallToolResult.isError``.
    """

    def test_run_command_outside_root_sets_is_error(
        self, jupyter_root, response_spy
    ):
        result, ui_spy = _invoke_run_command("/etc")
        assert result.get("is_error") is True
        ui_spy.assert_not_called()

    def test_run_command_nonexistent_dir_sets_is_error(
        self, jupyter_root, response_spy
    ):
        result, ui_spy = _invoke_run_command("does-not-exist")
        assert result.get("is_error") is True
        ui_spy.assert_not_called()

    def test_run_command_happy_path_no_is_error(
        self, jupyter_root, response_spy
    ):
        (jupyter_root / "work").mkdir()
        result, ui_spy = _invoke_run_command("work")
        # Successful call must NOT carry the is_error flag, or the SDK
        # would treat every legitimate response as a fault.
        assert "is_error" not in result or result["is_error"] is False

    def test_open_file_outside_root_sets_is_error(
        self, jupyter_root, response_spy
    ):
        result, ui_spy = _invoke_open_file("/etc/passwd")
        assert result.get("is_error") is True
        ui_spy.assert_not_called()


class TestRootNotSet:
    """``safe_jupyter_path`` raises ``RuntimeError`` (not ``ValueError``)
    when the workspace root hasn't been configured, so the tool's
    ``except ValueError`` block can't swallow a server-side
    misconfiguration as if it were an LLM-supplied bad path.
    """

    def test_run_command_propagates_runtime_error(
        self, monkeypatch, response_spy
    ):
        # No jupyter_root fixture: leaves _jupyter_root_dir at whatever
        # the prior test set, so explicitly clear it for this case.
        monkeypatch.setattr(util_mod, "_jupyter_root_dir", None)
        # The outer except Exception still catches RuntimeError and
        # renders an error response, but the response carries is_error
        # AND mentions "not set" rather than the LLM-facing "outside
        # allowed directory" wording. That distinction lets ops alerts
        # distinguish misconfig from LLM tool-call rejection.
        result, ui_spy = _invoke_run_command(".")
        assert result.get("is_error") is True
        text = result["content"][0]["text"]
        assert "not set" in text
        ui_spy.assert_not_called()
