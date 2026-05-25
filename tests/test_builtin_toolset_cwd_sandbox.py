# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Scope test for the embedded-terminal shell tool's working_directory.

The tool used to pass `working_directory` straight through to
`subprocess.Popen(cwd=...)`. An LLM-supplied path of '/etc' or '..' would
spawn a subprocess outside `jupyter_root_dir`. These tests pin the
``_get_safe_path`` gate that now blocks that traversal.
"""

import asyncio
import io
from unittest.mock import MagicMock, patch

import pytest

import notebook_intelligence.built_in_toolsets as toolsets
from notebook_intelligence.util import set_jupyter_root_dir


@pytest.fixture
def jupyter_root(tmp_path, monkeypatch):
    # Create a real subdir for the workspace so the parent tmp_path remains
    # available as an "outside the workspace" target for symlink tests.
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(toolsets, "get_jupyter_root_dir", lambda: str(root))
    set_jupyter_root_dir(str(root))
    return root


_SHELL_TOOL_CMD = ["echo", "hi"]


class _FakePopenProcess:
    """Minimal subprocess stand-in with concrete process-like attributes.

    A bare MagicMock leaks mock-valued ``pid``/streams into background
    asyncio waitpid helpers, which can explode with ``expected_pid > 0``
    type checks. Keep this fake small but process-shaped.
    """

    def __init__(self, returncode=0, stdout_text="", stderr_text=""):
        self.pid = 12345
        self.returncode = returncode
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)

    def wait(self):
        return self.returncode


def _shell_tool_calls(popen_spy):
    """Filter the Popen spy's call list to only those that originated from
    run_command_in_embedded_terminal. Patching ``subprocess.Popen`` is
    process-global, so other background threads (notably the bundled Claude
    Agent SDK on CI) can call into the spy during the patch window. The
    shell tool always passes ``shlex.split('echo hi')`` (a list); the
    Claude SDK passes a tuple. Filter on that shape plus the exact command
    so the security assertions don't depend on incidental noise calls.
    """
    out = []
    for call in popen_spy.call_args_list:
        first = call.args[0] if call.args else None
        if isinstance(first, list) and first == _SHELL_TOOL_CMD:
            out.append(call)
    return out


def _invoke(working_directory: str):
    """Drive run_command_in_embedded_terminal with a stubbed response and a
    Popen-spy so the test can observe whether a subprocess would have been
    spawned for the given working_directory.
    """
    # SimpleTool wraps the original async callable as `_tool_function`.
    tool = toolsets.run_command_in_embedded_terminal._tool_function
    response = MagicMock()
    popen_spy = MagicMock(return_value=_FakePopenProcess(stdout_text="hi\n"))
    with patch("notebook_intelligence.built_in_toolsets.subprocess.Popen", popen_spy):
        result = asyncio.run(
            tool(command="echo hi", working_directory=working_directory, response=response)
        )
    return result, popen_spy


def _invoke_jupyter_terminal(working_directory: str):
    """Same shape, for the run_command_in_jupyter_terminal sibling. The cwd
    is forwarded to a JupyterLab UI command, so the spy is on response's
    run_ui_command rather than on subprocess.Popen.
    """
    tool = toolsets.run_command_in_jupyter_terminal._tool_function
    response = MagicMock()

    async def fake_run_ui_command(cmd, payload):
        return "ok"

    response.run_ui_command.side_effect = fake_run_ui_command
    result = asyncio.run(
        tool(command="echo hi", working_directory=working_directory, response=response)
    )
    return result, response.run_ui_command


class TestEmbeddedTerminalCwdSandbox:
    def test_rejects_absolute_path_outside_jupyter_root(self, jupyter_root):
        result, popen_spy = _invoke("/etc")
        assert "outside allowed directory" in result
        assert _shell_tool_calls(popen_spy) == []

    def test_rejects_relative_traversal_outside_jupyter_root(self, jupyter_root):
        # `..` from the root resolves above the root.
        result, popen_spy = _invoke("../../..")
        assert "outside allowed directory" in result
        assert _shell_tool_calls(popen_spy) == []

    def test_rejects_nonexistent_directory(self, jupyter_root):
        result, popen_spy = _invoke("does-not-exist")
        assert "does not exist" in result
        assert _shell_tool_calls(popen_spy) == []

    def test_rejects_path_that_is_a_file_not_a_directory(self, jupyter_root):
        f = jupyter_root / "note.txt"
        f.write_text("hi")
        result, popen_spy = _invoke("note.txt")
        assert "not a directory" in result
        assert _shell_tool_calls(popen_spy) == []

    def test_allows_relative_subdirectory(self, jupyter_root):
        sub = jupyter_root / "work"
        sub.mkdir()
        result, popen_spy = _invoke("work")
        # When the path is valid, Popen is called with the sandboxed
        # absolute path (str of the resolved subdir). We filter the spy
        # call list to just the shell tool's own Popen invocation because
        # patching `subprocess.Popen` is process-global and other threads
        # (e.g. the bundled Claude Agent SDK on CI) can land calls in the
        # spy during the patch window.
        my_calls = _shell_tool_calls(popen_spy)
        assert len(my_calls) == 1
        kwargs = my_calls[0].kwargs
        assert kwargs["cwd"] == str(sub.resolve())
        # Tool returns its standard happy-path string even though we never
        # actually executed anything (Popen is a MagicMock).
        assert isinstance(result, str)

    def test_dot_means_jupyter_root(self, jupyter_root):
        result, popen_spy = _invoke(".")
        my_calls = _shell_tool_calls(popen_spy)
        assert len(my_calls) == 1
        kwargs = my_calls[0].kwargs
        assert kwargs["cwd"] == str(jupyter_root.resolve())

    def test_rejects_workspace_symlink_pointing_outside(self, jupyter_root, tmp_path):
        # A symlink inside the workspace pointing to /etc would let the LLM
        # escape via Path.resolve() chasing it. Pin that resolve() is called
        # before the relative_to() containment check.
        outside = tmp_path / "outside"
        outside.mkdir()
        link = jupyter_root / "escape"
        link.symlink_to(outside, target_is_directory=True)
        result, popen_spy = _invoke("escape")
        assert "outside allowed directory" in result
        assert _shell_tool_calls(popen_spy) == []

    def test_rejects_traversal_via_valid_subdir_prefix(self, jupyter_root):
        # `valid/../../..` resolves above the root even though the literal
        # prefix is a real subdir. Pins that resolve() collapses `..` before
        # the containment check.
        sub = jupyter_root / "valid"
        sub.mkdir()
        result, popen_spy = _invoke("valid/../../..")
        assert "outside allowed directory" in result
        assert _shell_tool_calls(popen_spy) == []

    def test_rejects_null_byte_in_path(self, jupyter_root):
        # pathlib raises ValueError on embedded null bytes. The fix's
        # try/except converts that to a tool-result error string without
        # spawning a subprocess. Pin so a future refactor that swallows the
        # exception cannot reopen the hole.
        result, popen_spy = _invoke("evil\x00")
        # Either the explicit "outside" branch (after pathlib normalizes) or
        # the pathlib-raised ValueError -> "Error: ..." string. Both are
        # acceptable; the load-bearing assertion is no-spawn.
        assert _shell_tool_calls(popen_spy) == []


class TestJupyterTerminalCwdSandbox:
    """Same security property for the sibling that opens a JupyterLab
    terminal via a UI command. The cwd is forwarded to the frontend; the
    terminal opens at any absolute path the user can read, so the sandbox
    must apply server-side before the UI bridge is called.
    """

    def test_rejects_absolute_path_outside_jupyter_root(self, jupyter_root):
        result, ui_spy = _invoke_jupyter_terminal("/etc")
        assert "outside allowed directory" in result
        ui_spy.assert_not_called()

    def test_rejects_relative_traversal_outside_jupyter_root(self, jupyter_root):
        result, ui_spy = _invoke_jupyter_terminal("../../..")
        assert "outside allowed directory" in result
        ui_spy.assert_not_called()

    def test_rejects_workspace_symlink_pointing_outside(self, jupyter_root, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        link = jupyter_root / "escape"
        link.symlink_to(outside, target_is_directory=True)
        result, ui_spy = _invoke_jupyter_terminal("escape")
        assert "outside allowed directory" in result
        ui_spy.assert_not_called()

    def test_allows_relative_subdirectory(self, jupyter_root):
        sub = jupyter_root / "work"
        sub.mkdir()
        result, ui_spy = _invoke_jupyter_terminal("work")
        # When the path is valid, the UI command receives the sandboxed
        # absolute path (str of the resolved subdir).
        assert ui_spy.call_count == 1
        payload = ui_spy.call_args.args[1]
        assert payload["cwd"] == str(sub.resolve())
