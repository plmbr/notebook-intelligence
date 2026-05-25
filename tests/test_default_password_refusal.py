# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Tests for the default-token-password guardrails on multi-tenant deployments.

The Copilot token's encryption password is configurable via
``NBI_GH_ACCESS_TOKEN_PASSWORD`` but defaults to a public literal. On a
shared-home cluster, an admin who leaves the default in place exposes
every user's token to anyone with a read primitive against
``user-data.json``. These tests pin two behaviors:

1. A one-shot WARNING fires whenever the default password is in use,
   escalated in tone when the directory holding ``user-data.json`` is
   readable beyond the owner.
2. When ``NBI_REFUSE_DEFAULT_TOKEN_PASSWORD_ON_SHARED_FS`` is set, the
   write is refused entirely under those conditions, unless the admin
   opts back in via ``NBI_ALLOW_DEFAULT_TOKEN_PASSWORD``.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys

import pytest

POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX mode bits are meaningless under Windows ACLs",
)


@pytest.fixture
def gh(monkeypatch, tmp_path):
    """Reload github_copilot pointed at a tmp_path user-data dir.

    The module captures ``access_token_password`` and ``user_data_file``
    at import time, so the fixture re-imports with a controlled
    environment + HOME to give each test a clean slate.
    """
    import notebook_intelligence.github_copilot as github_copilot

    monkeypatch.delenv("NBI_GH_ACCESS_TOKEN_PASSWORD", raising=False)
    monkeypatch.delenv("NBI_REFUSE_DEFAULT_TOKEN_PASSWORD_ON_SHARED_FS", raising=False)
    monkeypatch.delenv("NBI_ALLOW_DEFAULT_TOKEN_PASSWORD", raising=False)
    target_dir = tmp_path / ".jupyter" / "nbi"
    target_dir.mkdir(parents=True)
    monkeypatch.setattr(
        github_copilot, "user_data_file", str(target_dir / "user-data.json")
    )
    # Reset the per-process warn-once flag so each test gets a fresh log.
    monkeypatch.setattr(github_copilot, "_default_password_warned", False)
    return github_copilot


class TestDefaultPasswordWarning:
    def test_warns_when_default_password_in_use(self, gh, caplog):
        with caplog.at_level(logging.WARNING, logger="notebook_intelligence.github_copilot"):
            gh._warn_default_password_once()
        assert any(
            "default NBI_GH_ACCESS_TOKEN_PASSWORD" in r.message for r in caplog.records
        )

    def test_warns_only_once_per_process(self, gh, caplog):
        with caplog.at_level(logging.WARNING, logger="notebook_intelligence.github_copilot"):
            gh._warn_default_password_once()
            gh._warn_default_password_once()
        warnings = [
            r for r in caplog.records if "NBI_GH_ACCESS_TOKEN_PASSWORD" in r.message
        ]
        assert len(warnings) == 1

    def test_no_warning_when_password_overridden(self, gh, monkeypatch, caplog):
        monkeypatch.setattr(gh, "access_token_password", "per-user-secret")
        with caplog.at_level(logging.WARNING, logger="notebook_intelligence.github_copilot"):
            gh._warn_default_password_once()
        assert all(
            "NBI_GH_ACCESS_TOKEN_PASSWORD" not in r.message for r in caplog.records
        )

    @POSIX_ONLY
    def test_shared_dir_escalates_warning_message(self, gh, monkeypatch, caplog):
        # Loosen the dir mode and confirm the warning text changes to
        # call out the shared-host posture AND names the actual
        # directory so an operator triaging logs can find the file.
        target_dir = os.path.dirname(gh.user_data_file)
        os.chmod(target_dir, 0o755)
        with caplog.at_level(logging.WARNING, logger="notebook_intelligence.github_copilot"):
            gh._warn_default_password_once()
        msg = " ".join(r.message for r in caplog.records)
        assert "readable by group or other" in msg
        assert target_dir in msg

    def test_read_path_also_emits_warning_and_returns_plaintext(
        self, gh, caplog, tmp_path, monkeypatch
    ):
        # The read-side warn covers an exposed-state audit: an admin
        # who rotated to a per-user password but left an old
        # user-data.json on disk still hears the warning until the
        # process restarts AND the read path is exercised.
        #
        # The contract is "warn AND return the plaintext"; without the
        # second half a regression that aborts the read on warn would
        # silently log the user out. Write a token, then assert both.
        import base64
        import json

        from notebook_intelligence.util import encrypt_with_password

        ciphertext = encrypt_with_password(gh.access_token_password, b"ghu_token")
        b64 = base64.b64encode(ciphertext).decode("utf-8")
        with open(gh.user_data_file, "w") as f:
            json.dump({"github_access_token": b64}, f)

        with caplog.at_level(logging.WARNING, logger="notebook_intelligence.github_copilot"):
            plaintext = gh.read_stored_github_access_token()
        assert plaintext == "ghu_token"
        assert any(
            "NBI_GH_ACCESS_TOKEN_PASSWORD" in r.message for r in caplog.records
        )

    @POSIX_ONLY
    def test_warning_text_omits_dir_path_in_non_shared_branch(self, gh, caplog):
        # The escalated warning includes the directory; the non-shared
        # branch should NOT, otherwise log analysis can't distinguish
        # the two postures by message content alone.
        target_dir = os.path.dirname(gh.user_data_file)
        os.chmod(target_dir, 0o700)
        with caplog.at_level(logging.WARNING, logger="notebook_intelligence.github_copilot"):
            gh._warn_default_password_once()
        msg = " ".join(r.message for r in caplog.records)
        assert "NBI_GH_ACCESS_TOKEN_PASSWORD" in msg
        assert target_dir not in msg


@POSIX_ONLY
class TestRefuseWriteOnSharedFs:
    def _make_dir_shared(self, gh):
        target_dir = os.path.dirname(gh.user_data_file)
        os.chmod(target_dir, 0o755)
        return target_dir

    def test_refuse_disabled_by_default(self, gh):
        # Default behavior is unchanged: even with default password and
        # a permissive directory mode, the helper returns False so the
        # write proceeds.
        self._make_dir_shared(gh)
        assert gh._refuse_write_on_shared_default() is False

    def test_refuses_when_opted_in_and_dir_is_shared(self, gh, monkeypatch):
        self._make_dir_shared(gh)
        monkeypatch.setenv("NBI_REFUSE_DEFAULT_TOKEN_PASSWORD_ON_SHARED_FS", "1")
        assert gh._refuse_write_on_shared_default() is True

    def test_does_not_refuse_when_password_overridden(self, gh, monkeypatch):
        self._make_dir_shared(gh)
        monkeypatch.setenv("NBI_REFUSE_DEFAULT_TOKEN_PASSWORD_ON_SHARED_FS", "1")
        monkeypatch.setattr(gh, "access_token_password", "per-user-secret")
        assert gh._refuse_write_on_shared_default() is False

    def test_does_not_refuse_when_dir_is_owner_only(self, gh, monkeypatch):
        # 0o700 is the owner-only mode; the refusal is gated on
        # group/other readability so a single-user pod with a tightly-
        # scoped home is unaffected.
        target_dir = os.path.dirname(gh.user_data_file)
        os.chmod(target_dir, 0o700)
        monkeypatch.setenv("NBI_REFUSE_DEFAULT_TOKEN_PASSWORD_ON_SHARED_FS", "1")
        assert gh._refuse_write_on_shared_default() is False

    def test_admin_can_opt_back_in(self, gh, monkeypatch):
        # Admin acknowledges the risk: refusal disengages even with the
        # refuse env set, so a deployment that knowingly relaxed perms
        # can keep working through a transition.
        self._make_dir_shared(gh)
        monkeypatch.setenv("NBI_REFUSE_DEFAULT_TOKEN_PASSWORD_ON_SHARED_FS", "1")
        monkeypatch.setenv("NBI_ALLOW_DEFAULT_TOKEN_PASSWORD", "1")
        assert gh._refuse_write_on_shared_default() is False


@POSIX_ONLY
class TestWriteRefusalEndToEnd:
    def test_write_returns_false_when_refused(self, gh, monkeypatch, caplog):
        target_dir = os.path.dirname(gh.user_data_file)
        os.chmod(target_dir, 0o755)
        monkeypatch.setenv("NBI_REFUSE_DEFAULT_TOKEN_PASSWORD_ON_SHARED_FS", "1")
        with caplog.at_level(logging.ERROR, logger="notebook_intelligence.github_copilot"):
            ok = gh.write_github_access_token("ghu_test_token")
        assert ok is False
        # Nothing was written; the file should not exist.
        assert not os.path.exists(gh.user_data_file)
        # The error message must name the file so an operator can find it.
        assert any(
            "Refusing to write" in r.message and gh.user_data_file in r.message
            for r in caplog.records
        )

    def test_write_succeeds_when_refusal_not_engaged(self, gh, monkeypatch):
        # Sanity: with no refusal opt-in, the write goes through as
        # before. Pinning this prevents a regression where the guard
        # accidentally short-circuits the happy path.
        ok = gh.write_github_access_token("ghu_test_token")
        assert ok is True
        assert os.path.exists(gh.user_data_file)
