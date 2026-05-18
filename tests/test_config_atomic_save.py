"""Tests for atomic config writes in NBIConfig.

Pre-fix: ``open(target, 'w')`` truncates first, so a crash mid-write
leaves the config empty/partial and the next launch fails to load.
The fix uses a sibling tempfile + ``fsync`` + ``os.replace`` so the
visible state of ``target`` is either fully old or fully new — never
half-written.
"""

import json
import os
from pathlib import Path

import pytest

from notebook_intelligence.config import _atomic_write_json


class TestAtomicWriteJson:
    def test_creates_file_with_payload(self, tmp_path):
        target = tmp_path / "config.json"
        _atomic_write_json(str(target), {"a": 1, "b": "two"})
        assert json.loads(target.read_text()) == {"a": 1, "b": "two"}

    def test_replaces_existing_file_atomically(self, tmp_path):
        target = tmp_path / "config.json"
        target.write_text(json.dumps({"old": True}))
        _atomic_write_json(str(target), {"new": True})
        assert json.loads(target.read_text()) == {"new": True}

    def test_no_tempfile_left_behind_on_success(self, tmp_path):
        target = tmp_path / "config.json"
        _atomic_write_json(str(target), {"a": 1})
        leftover = [
            p for p in tmp_path.iterdir() if p.name != "config.json"
        ]
        assert leftover == []

    def test_failure_during_write_does_not_overwrite_existing(
        self, tmp_path, monkeypatch
    ):
        target = tmp_path / "config.json"
        target.write_text(json.dumps({"keep": "me"}))

        # Force ``json.dump`` to fail mid-write to simulate a crash.
        def boom(*args, **kwargs):
            raise IOError("disk full")

        monkeypatch.setattr("notebook_intelligence.config.json.dump", boom)

        with pytest.raises(IOError):
            _atomic_write_json(str(target), {"new": "payload"})

        # Old file is untouched (atomic swap never happened).
        assert json.loads(target.read_text()) == {"keep": "me"}

    def test_failure_cleans_up_tempfile(self, tmp_path, monkeypatch):
        target = tmp_path / "config.json"

        def boom(*args, **kwargs):
            raise IOError("disk full")

        monkeypatch.setattr("notebook_intelligence.config.json.dump", boom)

        with pytest.raises(IOError):
            _atomic_write_json(str(target), {"x": 1})

        # No dangling .tmp files.
        leftover = [p.name for p in tmp_path.iterdir()]
        assert leftover == []

    def test_indents_payload_for_human_diffs(self, tmp_path):
        # Same shape as the prior call — verify the on-disk format
        # stays human-readable (existing behavior).
        target = tmp_path / "config.json"
        _atomic_write_json(str(target), {"key": "value"})
        text = target.read_text()
        assert "\n" in text  # indented, not single-line

    def test_writes_through_symlink(self, tmp_path):
        # User pointed config.json at a shared location via symlink.
        # ``save()`` must update the linked-to file, not replace the link.
        real_dir = tmp_path / "shared"
        real_dir.mkdir()
        real_target = real_dir / "config.json"
        real_target.write_text(json.dumps({"old": True}))
        link = tmp_path / "config.json"
        link.symlink_to(real_target)

        _atomic_write_json(str(link), {"new": True})

        assert link.is_symlink()
        assert json.loads(real_target.read_text()) == {"new": True}

    def test_preserves_existing_file_mode(self, tmp_path):
        import os as _os
        target = tmp_path / "config.json"
        target.write_text(json.dumps({"old": True}))
        _os.chmod(target, 0o640)

        _atomic_write_json(str(target), {"new": True})

        # Mode bits preserved across the atomic swap.
        assert (target.stat().st_mode & 0o777) == 0o640

    def test_explicit_mode_overrides_existing(self, tmp_path):
        # The secrets case (e.g. ~/.jupyter/nbi/user-data.json): even if
        # the existing file was somehow widened to 0o644 by a prior
        # umask-default write, an explicit mode=0o600 must tighten it.
        import os as _os
        target = tmp_path / "user-data.json"
        target.write_text(json.dumps({"old": True}))
        _os.chmod(target, 0o644)

        _atomic_write_json(str(target), {"new": True}, mode=0o600)

        assert (target.stat().st_mode & 0o777) == 0o600

    def test_explicit_mode_on_first_create(self, tmp_path):
        # No existing file. Explicit mode still applies, so the secret
        # file starts at 0o600 from the very first write.
        target = tmp_path / "user-data.json"
        assert not target.exists()

        _atomic_write_json(str(target), {"secret": "x"}, mode=0o600)

        assert (target.stat().st_mode & 0o777) == 0o600

    def test_default_mode_preserves_existing(self, tmp_path):
        # Regression: passing no mode keeps the pre-fix behavior so
        # existing callers don't see their file mode tightened.
        import os as _os
        target = tmp_path / "config.json"
        target.write_text(json.dumps({"old": True}))
        _os.chmod(target, 0o644)

        _atomic_write_json(str(target), {"new": True})  # no mode arg

        assert (target.stat().st_mode & 0o777) == 0o644
