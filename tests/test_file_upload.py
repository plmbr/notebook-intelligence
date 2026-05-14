"""Tests for the file upload handler and upload directory management.

Covers:
- Temp directory creation and cleanup
- FileUploadHandler: successful uploads, missing file, path traversal protection
- Size cap enforcement (413 on exceed)
- Retention sweep of stale upload subdirs
"""

import json
import os
import shutil
import time
from unittest.mock import MagicMock

import pytest

import notebook_intelligence.extension as ext
from notebook_intelligence.extension import (
    FileUploadHandler,
    _get_upload_dir,
    _sweep_upload_dir,
)


@pytest.fixture
def upload_dir(tmp_path):
    """Point _upload_dir at a temp directory for the duration of the test."""
    original = ext._upload_dir
    ext._upload_dir = str(tmp_path)
    yield str(tmp_path)
    ext._upload_dir = original


@pytest.fixture
def reset_upload_dir():
    """Reset _upload_dir to None so _get_upload_dir creates a fresh one."""
    original = ext._upload_dir
    ext._upload_dir = None
    yield
    if ext._upload_dir and ext._upload_dir != original:
        shutil.rmtree(ext._upload_dir, ignore_errors=True)
    ext._upload_dir = original


def _make_handler(files=None):
    """Create a mock FileUploadHandler with the given request files."""
    handler = MagicMock(spec=FileUploadHandler)
    handler.request = MagicMock()
    handler.request.files = files or {}
    handler.set_status = MagicMock()
    handler.finish = MagicMock()
    # MagicMock(spec=...) does not expose the spec's class attributes; copy
    # them onto the instance so post() can read its tunables. Tests that
    # mutate the class attr expect the next call to _make_handler to
    # observe the new value.
    handler.upload_max_mb = FileUploadHandler.upload_max_mb
    handler.upload_retention_hours = FileUploadHandler.upload_retention_hours
    return handler


def _parse_response(handler):
    return json.loads(handler.finish.call_args[0][0])


# ---------------------------------------------------------------------------
# _get_upload_dir
# ---------------------------------------------------------------------------

class TestGetUploadDir:
    def test_creates_directory(self, reset_upload_dir):
        result = _get_upload_dir()
        assert os.path.isdir(result)
        assert "nbi-uploads-" in result

    def test_returns_same_directory_on_repeated_calls(self, reset_upload_dir):
        first = _get_upload_dir()
        second = _get_upload_dir()
        assert first == second


# ---------------------------------------------------------------------------
# FileUploadHandler
# ---------------------------------------------------------------------------

class TestFileUploadHandler:
    def test_returns_400_when_no_file_provided(self):
        handler = _make_handler(files={})
        FileUploadHandler.post(handler)
        handler.set_status.assert_called_once_with(400)
        assert "No file provided" in _parse_response(handler)["error"]

    def test_returns_400_when_file_list_empty(self):
        handler = _make_handler(files={"file": []})
        FileUploadHandler.post(handler)
        handler.set_status.assert_called_once_with(400)

    def test_successful_text_upload(self, upload_dir):
        file_body = b"hello world"
        handler = _make_handler(files={
            "file": [{"filename": "test.txt", "body": file_body}]
        })

        FileUploadHandler.post(handler)

        response = _parse_response(handler)
        assert response["filename"] == "test.txt"
        assert response["serverPath"].startswith(upload_dir)
        with open(response["serverPath"], "rb") as f:
            assert f.read() == file_body

    def test_binary_file_upload(self, upload_dir):
        file_body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        handler = _make_handler(files={
            "file": [{"filename": "screenshot.png", "body": file_body}]
        })

        FileUploadHandler.post(handler)

        response = _parse_response(handler)
        assert response["filename"] == "screenshot.png"
        with open(response["serverPath"], "rb") as f:
            assert f.read() == file_body

    def test_path_traversal_protection(self, upload_dir):
        handler = _make_handler(files={
            "file": [{"filename": "../../../etc/passwd", "body": b"sneaky"}]
        })

        FileUploadHandler.post(handler)

        response = _parse_response(handler)
        assert response["filename"] == "passwd"
        assert response["serverPath"].startswith(upload_dir)

    def test_missing_filename_defaults_to_upload(self, upload_dir):
        handler = _make_handler(files={
            "file": [{"body": b"data"}]
        })

        FileUploadHandler.post(handler)

        assert _parse_response(handler)["filename"] == "upload"

    def test_unique_subdirectories_per_upload(self, upload_dir):
        paths = []
        for i in range(3):
            handler = _make_handler(files={
                "file": [{"filename": "same.txt", "body": f"v{i}".encode()}]
            })
            FileUploadHandler.post(handler)
            paths.append(_parse_response(handler)["serverPath"])

        assert len(set(paths)) == 3
        for p in paths:
            assert os.path.isfile(p)


# ---------------------------------------------------------------------------
# Size cap
# ---------------------------------------------------------------------------

@pytest.fixture
def upload_max_mb():
    """Restore the class-level cap after a test mutates it."""
    original = FileUploadHandler.upload_max_mb
    yield
    FileUploadHandler.upload_max_mb = original


class TestUploadSizeCap:
    def test_rejects_oversize_with_413(self, upload_dir, upload_max_mb):
        FileUploadHandler.upload_max_mb = 1
        # 1 MB + 1 byte; trips the 1 MB cap.
        oversize = b"x" * (1 * 1024 * 1024 + 1)
        handler = _make_handler(files={
            "file": [{"filename": "big.bin", "body": oversize}]
        })

        FileUploadHandler.post(handler)

        handler.set_status.assert_called_once_with(413)
        response = _parse_response(handler)
        assert "1 MB" in response["error"]

    def test_accepts_when_under_cap(self, upload_dir, upload_max_mb):
        FileUploadHandler.upload_max_mb = 1
        body = b"x" * 1024
        handler = _make_handler(files={
            "file": [{"filename": "small.bin", "body": body}]
        })

        FileUploadHandler.post(handler)

        handler.set_status.assert_not_called()
        assert _parse_response(handler)["filename"] == "small.bin"

    def test_cap_zero_disables_check(self, upload_dir, upload_max_mb):
        FileUploadHandler.upload_max_mb = 0
        # Would trip a 1 MB cap; with 0 (disabled) it should succeed.
        body = b"x" * (5 * 1024 * 1024)
        handler = _make_handler(files={
            "file": [{"filename": "big.bin", "body": body}]
        })

        FileUploadHandler.post(handler)

        handler.set_status.assert_not_called()
        assert os.path.getsize(_parse_response(handler)["serverPath"]) == len(body)


# ---------------------------------------------------------------------------
# Retention sweep
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_sweep_throttle():
    """Drop the rate-limit timestamp so each test can trigger a fresh sweep."""
    ext._last_sweep_at = 0.0
    yield
    ext._last_sweep_at = 0.0


class TestSweepUploadDir:
    def test_zero_retention_skips_sweep(self, upload_dir):
        stale = os.path.join(upload_dir, "stale-bundle")
        os.makedirs(stale)
        # Mark as ancient: 100 hours old.
        old_mtime = time.time() - 100 * 3600
        os.utime(stale, (old_mtime, old_mtime))

        _sweep_upload_dir(retention_hours=0)

        assert os.path.isdir(stale)

    def test_removes_stale_subdir_preserves_fresh(self, upload_dir):
        stale = os.path.join(upload_dir, "stale-bundle")
        fresh = os.path.join(upload_dir, "fresh-bundle")
        os.makedirs(stale)
        os.makedirs(fresh)
        old_mtime = time.time() - 48 * 3600  # 48h ago
        os.utime(stale, (old_mtime, old_mtime))

        _sweep_upload_dir(retention_hours=24)

        assert not os.path.exists(stale)
        assert os.path.isdir(fresh)

    def test_handles_missing_root(self, tmp_path):
        # Point _upload_dir at a path that doesn't exist; sweep must not raise.
        original = ext._upload_dir
        ext._upload_dir = str(tmp_path / "nonexistent")
        try:
            _sweep_upload_dir(retention_hours=1)  # no-op, no exception
        finally:
            ext._upload_dir = original

    def test_ignores_non_directories(self, upload_dir):
        rogue = os.path.join(upload_dir, "rogue.txt")
        with open(rogue, "wb") as fh:
            fh.write(b"data")
        old_mtime = time.time() - 100 * 3600
        os.utime(rogue, (old_mtime, old_mtime))

        _sweep_upload_dir(retention_hours=1)

        assert os.path.isfile(rogue)

    def test_sweep_runs_after_successful_upload(self, upload_dir):
        stale = os.path.join(upload_dir, "stale-bundle")
        os.makedirs(stale)
        old_mtime = time.time() - 100 * 3600
        os.utime(stale, (old_mtime, old_mtime))

        original = FileUploadHandler.upload_retention_hours
        FileUploadHandler.upload_retention_hours = 24
        try:
            handler = _make_handler(files={
                "file": [{"filename": "new.txt", "body": b"data"}]
            })
            FileUploadHandler.post(handler)
        finally:
            FileUploadHandler.upload_retention_hours = original

        # The successful upload's own subdir survives; the stale one is gone.
        assert not os.path.exists(stale)
        new_path = _parse_response(handler)["serverPath"]
        assert os.path.isfile(new_path)

    def test_rate_limit_skips_recent_sweep(self, upload_dir):
        # A sweep within the throttle window must not re-walk the dir.
        ext._last_sweep_at = time.time()  # Just swept; cooldown active.
        stale = os.path.join(upload_dir, "stale-bundle")
        os.makedirs(stale)
        old_mtime = time.time() - 100 * 3600
        os.utime(stale, (old_mtime, old_mtime))

        _sweep_upload_dir(retention_hours=24)

        # Throttle suppressed the second sweep; stale subdir is still present.
        assert os.path.isdir(stale)
