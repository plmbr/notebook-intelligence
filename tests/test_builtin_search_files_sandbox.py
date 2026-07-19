"""Sandbox tests for the built-in search_files tool.

``read_file`` routes every path through ``safe_jupyter_path`` before
opening; ``search_files`` must apply the same gate to each glob match so
outbound workspace symlinks cannot leak host file contents.
"""

import asyncio
import os
import tempfile

import pytest

import notebook_intelligence.built_in_toolsets as toolsets
from notebook_intelligence.util import get_jupyter_root_dir, set_jupyter_root_dir


def _symlinks_supported() -> bool:
    """Whether this platform/process can create symlinks.

    Windows only permits symlink creation with elevated privileges or
    Developer Mode, so the symlink sandbox tests are skipped where they
    cannot run rather than reported as spurious failures.
    """
    with tempfile.TemporaryDirectory() as td:
        target = os.path.join(td, "target")
        link = os.path.join(td, "link")
        open(target, "w").close()
        try:
            os.symlink(target, link)
            return True
        except (OSError, NotImplementedError):
            return False


requires_symlinks = pytest.mark.skipif(
    not _symlinks_supported(),
    reason="symlink creation is not supported on this platform",
)


@pytest.fixture
def jupyter_root(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(toolsets, "get_jupyter_root_dir", lambda: str(root))
    # set_jupyter_root_dir mutates process-global state, which monkeypatch
    # cannot restore for us; save and restore it so tests stay independent
    # of execution order.
    previous_root = get_jupyter_root_dir()
    set_jupyter_root_dir(str(root))
    try:
        yield root
    finally:
        set_jupyter_root_dir(previous_root)


def _search_files(pattern: str, **kwargs) -> str:
    tool = toolsets.search_files._tool_function
    return asyncio.run(tool(pattern=pattern, **kwargs))


class TestSearchFilesSymlinkSandbox:
    @requires_symlinks
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
        assert "No files found" in result

    def test_reads_legitimate_workspace_file(self, jupyter_root):
        target = jupyter_root / "notes.txt"
        target.write_text("hello workspace\n", encoding="utf-8")

        result = _search_files(
            pattern="notes.txt",
            directory=".",
            content_pattern="workspace",
        )

        assert "hello workspace" in result

    def test_rejects_parent_traversal_pattern(self, jupyter_root, tmp_path):
        # An outbound ".." pattern must be refused before glob() runs, so
        # the tool never stats or reads outside the workspace.
        outside = tmp_path / "secret.txt"
        outside.write_text("TOP_SECRET_DATA\n", encoding="utf-8")

        result = _search_files(
            pattern="../secret.txt",
            directory=".",
            content_pattern="TOP_SECRET",
        )

        assert "TOP_SECRET_DATA" not in result
        assert "not allowed" in result

    def test_traversal_rejection_does_not_leak_existence(
        self, jupyter_root, tmp_path
    ):
        # The rejection is pattern-based and must be identical whether or
        # not the outside target exists, so it cannot be used as an
        # existence oracle for arbitrary host paths.
        present = tmp_path / "present.txt"
        present.write_text("data\n", encoding="utf-8")

        hit_present = _search_files(pattern="../present.txt", directory=".")
        hit_absent = _search_files(pattern="../nope.txt", directory=".")

        assert "not allowed" in hit_present
        assert hit_present.replace("present", "X") == hit_absent.replace(
            "nope", "X"
        )

    @requires_symlinks
    def test_outbound_symlink_target_existence_not_revealed(
        self, jupyter_root, tmp_path
    ):
        # is_file() must not be called on a candidate before the sandbox
        # gate resolves it, or an outbound symlink whose target exists
        # would be admitted-then-skipped while a broken one is filtered
        # out earlier, leaking outside-path existence via the reply.
        existing_target = tmp_path / "exists.txt"
        existing_target.write_text("TOP_SECRET_DATA\n", encoding="utf-8")
        (jupyter_root / "link_present").symlink_to(existing_target)
        (jupyter_root / "link_absent").symlink_to(tmp_path / "missing.txt")

        present = _search_files(pattern="link_present", directory=".")
        absent = _search_files(pattern="link_absent", directory=".")

        assert "TOP_SECRET_DATA" not in present
        # Responses differ only by the echoed pattern name, never by
        # whether the outbound target exists.
        assert present.replace("link_present", "L") == absent.replace(
            "link_absent", "L"
        )

    @requires_symlinks
    def test_does_not_descend_outbound_symlink_directory(
        self, jupyter_root, tmp_path
    ):
        # A pattern that descends a symlinked directory (link -> /outside)
        # must not enumerate or read the outside tree. Enumeration never
        # crosses a symlinked directory, so the outside contents are never
        # matched.
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_text("TOP_SECRET_DATA\n", encoding="utf-8")
        (jupyter_root / "link").symlink_to(outside_dir, target_is_directory=True)
        (jupyter_root / "real.txt").write_text("in workspace\n", encoding="utf-8")

        via_link = _search_files(
            pattern="link/*.txt", directory=".", content_pattern="TOP_SECRET"
        )
        assert "TOP_SECRET_DATA" not in via_link
        assert "No files found" in via_link

        # A legitimate recursive search still returns in-workspace files and
        # never the symlinked-directory target.
        recursive = _search_files(pattern="**/*.txt", directory=".")
        assert "real.txt" in recursive
        assert "secret.txt" not in recursive

    def test_supports_glob_character_classes(self, jupyter_root):
        # Bracket expressions are standard glob syntax and must keep working.
        (jupyter_root / "mod.pyc").write_text("x\n", encoding="utf-8")
        (jupyter_root / "mod.pyo").write_text("y\n", encoding="utf-8")
        (jupyter_root / "mod.py").write_text("z\n", encoding="utf-8")

        result = _search_files(pattern="*.py[co]", directory=".")

        assert "mod.pyc" in result
        assert "mod.pyo" in result
        # Plain "mod.py" is not matched by "*.py[co]".
        assert "matching '*.py[co]'" in result
        assert "\nFile: mod.py\n" not in result and "mod.py:" not in result

    def test_nonrecursive_pattern_stays_shallow(self, jupyter_root):
        # A pattern without "**" must only match the current directory level
        # (as Path.glob does), so a large subtree is not walked for a simple
        # search.
        (jupyter_root / "top.py").write_text("a\n", encoding="utf-8")
        nested = jupyter_root / "sub"
        nested.mkdir()
        (nested / "deep.py").write_text("b\n", encoding="utf-8")

        result = _search_files(pattern="*.py", directory=".")

        assert "top.py" in result
        assert "deep.py" not in result

    def test_dot_path_components_are_normalized(self, jupyter_root):
        # "." components are a no-op, matching Path.glob: "./*.py" scans the
        # current directory and "sub/./*.txt" scans the subdirectory, rather
        # than looking for an entry literally named ".".
        (jupyter_root / "top.py").write_text("a\n", encoding="utf-8")
        nested = jupyter_root / "sub"
        nested.mkdir()
        (nested / "note.txt").write_text("b\n", encoding="utf-8")

        here = _search_files(pattern="./*.py", directory=".")
        assert "top.py" in here

        nested_result = _search_files(pattern="sub/./*.txt", directory=".")
        assert "note.txt" in nested_result

    def test_file_pattern_is_path_aware(self, jupyter_root):
        # file_pattern keeps its original right-anchored path matching, so a
        # relative-path glob narrows by location, not just basename.
        (jupyter_root / "top.py").write_text("a\n", encoding="utf-8")
        nested = jupyter_root / "sub"
        nested.mkdir()
        (nested / "inner.py").write_text("b\n", encoding="utf-8")

        result = _search_files(
            pattern="**/*", directory=".", file_pattern="sub/*.py"
        )

        assert "inner.py" in result
        assert "top.py" not in result

    @requires_symlinks
    def test_in_workspace_symlink_directory_is_searchable(self, jupyter_root):
        # A symlinked directory that resolves inside the workspace is safe and
        # must remain searchable (Path.glob parity), unlike an outbound one.
        real_dir = jupyter_root / "real"
        real_dir.mkdir()
        (real_dir / "found.txt").write_text("hello inside\n", encoding="utf-8")
        (jupyter_root / "link").symlink_to(real_dir, target_is_directory=True)

        via_link = _search_files(
            pattern="link/*.txt", directory=".", content_pattern="hello"
        )
        assert "hello inside" in via_link

        recursive = _search_files(pattern="**/*.txt", directory=".")
        assert "found.txt" in recursive

    @requires_symlinks
    def test_symlink_directory_cycle_terminates(self, jupyter_root):
        # A symlink cycle inside the workspace must not loop forever; **
        # recursion follows real directories only, so the cycle is never
        # entered. The pytest-timeout plugin would otherwise flag a hang.
        sub = jupyter_root / "sub"
        sub.mkdir()
        (sub / "real.txt").write_text("data\n", encoding="utf-8")
        # sub/loop -> sub  (a cycle if a "**" pattern were to follow symlinks)
        (sub / "loop").symlink_to(sub, target_is_directory=True)

        result = _search_files(pattern="**/*.txt", directory=".")
        assert "real.txt" in result

    @pytest.mark.skipif(
        os.name == "nt",
        reason="glob is case-insensitive on Windows (platform-default fnmatch)",
    )
    def test_pattern_matching_is_case_sensitive_on_posix(self, jupyter_root):
        # Platform-default case sensitivity is preserved: on POSIX, "*.PY"
        # does not match "foo.py" (matching Path.glob, not the old always-
        # case-sensitive fnmatchcase / a case-insensitive regression).
        (jupyter_root / "foo.py").write_text("x\n", encoding="utf-8")

        result = _search_files(pattern="*.PY", directory=".")
        assert "foo.py" not in result
