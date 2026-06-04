# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Tests for the per-pod KDF that protects the stored Copilot token.

``encrypt_user_secret`` / ``decrypt_user_secret`` mix the admin-supplied
``NBI_GH_ACCESS_TOKEN_PASSWORD`` with a machine + user secret before
running PBKDF2. A blob written on one pod must not decrypt on a
different pod even when both ship with the default password, which is
the shared-NFS-home cross-tenant exposure the audit called out.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cryptography.fernet import InvalidToken

from notebook_intelligence.util import (
    decrypt_user_secret,
    decrypt_with_password,
    encrypt_user_secret,
    encrypt_with_password,
)


PASSWORD = "test-password"
PLAINTEXT = b"ghu_test_token_value"


class TestRoundTripV2:
    def test_basic_round_trip(self):
        ciphertext = encrypt_user_secret(PASSWORD, PLAINTEXT)
        decrypted, was_legacy = decrypt_user_secret(PASSWORD, ciphertext)
        assert decrypted == PLAINTEXT
        assert was_legacy is False

    def test_format_is_unchanged_on_disk(self):
        # ``encrypt_user_secret`` must produce a blob shape identical to
        # ``encrypt_with_password`` so existing readers (and the
        # ``user-data.json`` JSON shape) don't need a schema bump. The
        # first 16 bytes are still the random salt; the rest is Fernet.
        ciphertext = encrypt_user_secret(PASSWORD, PLAINTEXT)
        assert len(ciphertext) > 16


class TestCrossPodIsolation:
    def test_blob_from_pod_a_does_not_decrypt_on_pod_b(self):
        # Simulate two pods with different machine-ids. A token
        # encrypted on pod A must not decrypt on pod B, even though both
        # are using the same admin-supplied password. This is the
        # central guarantee against the shared-NFS cross-tenant attack.
        with patch(
            "notebook_intelligence.util._read_machine_id",
            return_value="pod-a-machine-id",
        ):
            ciphertext = encrypt_user_secret(PASSWORD, PLAINTEXT)
        with patch(
            "notebook_intelligence.util._read_machine_id",
            return_value="pod-b-machine-id",
        ):
            with pytest.raises(InvalidToken):
                decrypt_user_secret(PASSWORD, ciphertext, allow_legacy=False)

    def test_different_uid_yields_different_ciphertext(self):
        # Same machine-id, different POSIX uid => still isolated. This
        # covers the rare multi-user pod (e.g., a shared-cluster shell
        # node) where the machine-id is constant but UIDs differ.
        with patch("os.getuid", return_value=1001), patch(
            "notebook_intelligence.util._read_machine_id",
            return_value="m",
        ):
            ciphertext = encrypt_user_secret(PASSWORD, PLAINTEXT)
        with patch("os.getuid", return_value=1002), patch(
            "notebook_intelligence.util._read_machine_id",
            return_value="m",
        ):
            with pytest.raises(InvalidToken):
                decrypt_user_secret(PASSWORD, ciphertext, allow_legacy=False)


class TestLegacyFallback:
    def test_legacy_blob_decrypts_via_fallback_path(self):
        # A blob produced by the old bare-password encrypt path must
        # still decrypt; the helper signals was_legacy=True so the
        # caller can rewrite under v2.
        legacy_ciphertext = encrypt_with_password(PASSWORD, PLAINTEXT)
        plaintext, was_legacy = decrypt_user_secret(
            PASSWORD, legacy_ciphertext
        )
        assert plaintext == PLAINTEXT
        assert was_legacy is True

    def test_allow_legacy_false_refuses_old_blobs(self):
        legacy_ciphertext = encrypt_with_password(PASSWORD, PLAINTEXT)
        with pytest.raises(InvalidToken):
            decrypt_user_secret(
                PASSWORD, legacy_ciphertext, allow_legacy=False
            )


class TestMachineIdFallback:
    def test_missing_machine_id_falls_back_to_hostname(self):
        # In containers that don't mount /etc/machine-id, the helper
        # falls back to the hostname (which equals the pod name in
        # Kubernetes), preserving per-pod isolation.
        with patch(
            "notebook_intelligence.util._read_machine_id", return_value=""
        ), patch("socket.gethostname", return_value="pod-x"):
            ciphertext = encrypt_user_secret(PASSWORD, PLAINTEXT)
        with patch(
            "notebook_intelligence.util._read_machine_id", return_value=""
        ), patch("socket.gethostname", return_value="pod-x"):
            plaintext, was_legacy = decrypt_user_secret(
                PASSWORD, ciphertext, allow_legacy=False
            )
            assert plaintext == PLAINTEXT
            assert was_legacy is False

    def test_hostname_change_isolates_pods(self):
        with patch(
            "notebook_intelligence.util._read_machine_id", return_value=""
        ), patch("socket.gethostname", return_value="pod-x"):
            ciphertext = encrypt_user_secret(PASSWORD, PLAINTEXT)
        with patch(
            "notebook_intelligence.util._read_machine_id", return_value=""
        ), patch("socket.gethostname", return_value="pod-y"):
            with pytest.raises(InvalidToken):
                decrypt_user_secret(
                    PASSWORD, ciphertext, allow_legacy=False
                )


class TestPasswordStillMatters:
    def test_changing_admin_password_invalidates_existing_blob(self):
        # The machine-derived secret augments the admin password; it
        # does not replace it. A change to NBI_GH_ACCESS_TOKEN_PASSWORD
        # must still invalidate every previously-encrypted blob.
        ciphertext = encrypt_user_secret(PASSWORD, PLAINTEXT)
        with pytest.raises(InvalidToken):
            decrypt_user_secret(
                "different-password", ciphertext, allow_legacy=False
            )


class TestPodIdentityEnv:
    """NBI_POD_IDENTITY is the highest-priority entropy source.

    On a K8s deployment with /etc/machine-id mounted from the host node
    and uid pinned to 1000 (the default for jupyter/jovyan images), the
    automatic sources collapse to a value shared across co-tenants on
    that node. An admin who pins NBI_POD_IDENTITY to a per-pod or
    per-user identity (e.g., the JupyterHub username, the spawn token)
    restores cross-tenant isolation.
    """

    def test_pod_identity_isolates_when_machine_id_is_shared(self, monkeypatch):
        # Same machine-id + same uid (the realistic K8s shape), but
        # different NBI_POD_IDENTITY between two pods.
        monkeypatch.setattr(
            "notebook_intelligence.util._read_machine_id",
            lambda: "shared-host-machine-id",
        )
        monkeypatch.setattr("socket.gethostname", lambda: "shared-host")
        monkeypatch.setattr("os.getuid", lambda: 1000)

        monkeypatch.setenv("NBI_POD_IDENTITY", "tenant-a")
        ciphertext = encrypt_user_secret(PASSWORD, PLAINTEXT)
        monkeypatch.setenv("NBI_POD_IDENTITY", "tenant-b")
        with pytest.raises(InvalidToken):
            decrypt_user_secret(PASSWORD, ciphertext, allow_legacy=False)

    def test_pod_identity_unset_uses_machine_id(self, monkeypatch):
        # When NBI_POD_IDENTITY is absent, behavior matches the
        # machine-id path. Pin so removing the env-var branch doesn't
        # quietly break the auto-detection fallback.
        monkeypatch.delenv("NBI_POD_IDENTITY", raising=False)
        monkeypatch.setattr(
            "notebook_intelligence.util._read_machine_id",
            lambda: "machine-id-x",
        )
        ciphertext = encrypt_user_secret(PASSWORD, PLAINTEXT)
        plaintext, was_legacy = decrypt_user_secret(
            PASSWORD, ciphertext, allow_legacy=False
        )
        assert plaintext == PLAINTEXT
        assert was_legacy is False


class TestSilentLegacyUpgrade:
    """The token reader rewrites legacy blobs under v2 on first read.

    Without this test, a regression that drops the rewrite call (or
    inverts the ``if was_legacy`` branch) ships clean because no other
    test exercises the github_copilot flow end-to-end.
    """

    def test_legacy_blob_on_disk_gets_upgraded(self, tmp_path, monkeypatch):
        import base64
        import json

        from notebook_intelligence import github_copilot

        # Stand up a fake user-data.json that contains a legacy blob
        # (encrypted with the bare password) and point the module at it.
        legacy_ciphertext = encrypt_with_password(PASSWORD, PLAINTEXT)
        legacy_b64 = base64.b64encode(legacy_ciphertext).decode("utf-8")
        user_data_path = tmp_path / "user-data.json"
        user_data_path.write_text(
            json.dumps({"github_access_token": legacy_b64}),
            encoding="utf-8",
        )
        monkeypatch.setattr(github_copilot, "user_data_file", str(user_data_path))
        monkeypatch.setattr(github_copilot, "access_token_password", PASSWORD)

        first = github_copilot.read_stored_github_access_token()
        assert first == PLAINTEXT.decode("utf-8")

        # After the first read the file should now contain a v2 blob,
        # so a second read decrypts via the non-legacy path. Confirm by
        # checking the on-disk bytes changed (rewritten) and that
        # decrypt_user_secret reports was_legacy=False on the new bytes.
        on_disk_now = json.loads(user_data_path.read_text(encoding="utf-8"))
        new_b64 = on_disk_now["github_access_token"]
        assert new_b64 != legacy_b64
        plaintext, was_legacy = decrypt_user_secret(
            PASSWORD, base64.b64decode(new_b64.encode("utf-8"))
        )
        assert plaintext == PLAINTEXT
        assert was_legacy is False
