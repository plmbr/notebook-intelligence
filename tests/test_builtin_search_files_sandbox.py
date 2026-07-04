"""Sandbox tests for the built-in search_files tool.

``read_file`` routes every path through ``safe_jupyter_path`` before
opening; ``search_files`` must apply the same gate to each glob match so
outbound workspace symlinks cannot leak host file contents.
"""

import asyncio

import pytest

import notebook_intelligence.built_in_toolsets as toolsets
from notebook_intelligence.util import set_jupyter_root_dir


@pytest.fixture
def jupyter_root(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(toolsets, "get_jupyter_root_dir", lambda: str(root))
    set_jupyter_root_dir(str(root))
    return root


def _search_files(pattern: str, **kwargs) -> str:
    tool = toolsets.search_files._tool_function
    return asyncio.run(tool(pattern=pattern, **kwargs))


class TestSearchFilesSymlinkSandbox:
    def test_skips_outbound_symlink_when_searching_content(
        self, jupyter_root, tmp_path
    ):
        outside = tmp_path / "secret.txt"
        outside.write_text("TOP_SECRET_DATA\n", encoding="utf-8")
        link = jupyter_root / "leak.txt"
        link.symlink_to(outside)

        result = _search_files(
            pattern="leak.txt",
            directory=".",
            content_pattern="TOP_SECRET",
        )

        assert "TOP_SECRET_DATA" not in result
        assert "No matches found" in result

    def test_reads_legitimate_workspace_file(self, jupyter_root):
        target = jupyter_root / "notes.txt"
        target.write_text("hello workspace\n", encoding="utf-8")

        result = _search_files(
            pattern="notes.txt",
            directory=".",
            content_pattern="workspace",
        )

        assert "hello workspace" in result
