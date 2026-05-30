"""Regression tests for the built-in file read tool output cap."""

import asyncio

import pytest

import notebook_intelligence.built_in_toolsets as toolsets
from notebook_intelligence import util as util_mod


@pytest.fixture
def jupyter_root(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(util_mod, "_jupyter_root_dir", str(root))
    return root


def _read_file(file_path: str, **kwargs) -> str:
    tool = toolsets.read_file._tool_function
    return asyncio.run(tool(file_path=file_path, **kwargs))


class TestReadFileOutputCap:
    def test_small_file_is_returned_verbatim(self, jupyter_root):
        target = jupyter_root / "small.txt"
        target.write_text("hello\nworld\n", encoding="utf-8")

        result = _read_file("small.txt")

        assert result == "Content of 'small.txt' (lines 1-2):\nhello\nworld\n"
        assert "[output truncated]" not in result

    def test_oversize_output_is_truncated_with_marker(self, jupyter_root):
        target = jupyter_root / "huge.txt"
        target.write_text("a" * 40_500, encoding="utf-8")

        result = _read_file("huge.txt")

        assert result.startswith("Content of 'huge.txt' (lines 1-1):\n")
        assert result.endswith("[output truncated]")
        assert "a" * 40_500 not in result
        assert len(result.encode("utf-8")) <= 40_000

    def test_multibyte_utf8_content_respects_byte_budget(self, jupyter_root):
        target = jupyter_root / "multibyte.txt"
        target.write_text("你🙂" * 20, encoding="utf-8")

        result = _read_file("multibyte.txt", max_output_tokens=16)

        assert result.endswith("[output truncated]")
        assert len(result.encode("utf-8")) <= 64
        visible = result.split(":\n", 1)[1].removesuffix("\n[output truncated]")
        assert visible
        for ch in visible:
            assert ch in {"你", "🙂"}

    def test_non_utf8_file_returns_encoding_error(self, jupyter_root):
        target = jupyter_root / "latin1.bin"
        target.write_bytes(b"\xff\xfe\xfd\xfc")

        result = _read_file("latin1.bin")

        assert "is not a text file or uses an unsupported encoding" in result
        assert "[output truncated]" not in result
