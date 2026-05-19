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
from notebook_intelligence.util import set_jupyter_root_dir


@pytest.fixture
def jupyter_root(tmp_path):
    # Workspace lives under tmp_path so the parent remains available as an
    # "outside the workspace" target for symlink + absolute-path tests.
    root = tmp_path / "workspace"
    root.mkdir()
    set_jupyter_root_dir(str(root))
    yield root
    set_jupyter_root_dir(None)


@pytest.fixture
def response_spy():
    # The tool calls `claude.get_current_response().run_ui_command(...)`.
    # Inject a spy so each test can observe whether the UI command was
    # invoked at all, and with what payload when it was.
    response = MagicMock()

    async def fake_run_ui_command(cmd, payload):
        return "ok"

    response.run_ui_command.side_effect = fake_run_ui_command
    claude_mod.set_current_response(response)
    yield response
    claude_mod.set_current_response(None)


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
        # The sandboxed absolute path is forwarded, not the LLM-supplied
        # relative value, so any intermediate that does cwd-relative
        # resolution can't double-resolve into a different file.
        assert payload["path"] == str((jupyter_root / "notebook.ipynb").resolve())

    def test_allows_file_that_does_not_exist_yet(
        self, jupyter_root, response_spy
    ):
        # docmanager:open is also used to open files about to be created.
        # The security gate must not require existence (that's a UX
        # concern, surfaced by docmanager).
        result, ui_spy = _invoke_open_file("brand-new.ipynb")
        assert ui_spy.call_count == 1
        payload = ui_spy.call_args.args[1]
        assert payload["path"].endswith("brand-new.ipynb")
