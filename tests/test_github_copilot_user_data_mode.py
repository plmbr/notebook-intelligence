# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Pin the file-mode contract on `~/.jupyter/nbi/user-data.json`.

The file holds the encrypted GitHub Copilot access token. A default
umask write produces 0o644, which on shared-home topologies (NFS,
classroom labs) lets other users read the ciphertext and brute-force
the default password. The fix forces 0o600 on every write so the file
is never group/world-readable, regardless of prior state.
"""

import json
import os
import stat

import pytest

from notebook_intelligence import github_copilot


@pytest.fixture
def temp_user_data(tmp_path, monkeypatch):
    """Redirect the module-level `user_data_file` to a tmp_path location
    so the test never touches the real ~/.jupyter/nbi/."""
    target = tmp_path / "user-data.json"
    monkeypatch.setattr(github_copilot, "user_data_file", str(target))
    return target


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class TestUserDataFileMode:
    def test_first_write_is_0o600(self, temp_user_data):
        assert not temp_user_data.exists()
        github_copilot.write_github_access_token("ghp_test_token")
        assert temp_user_data.exists()
        # File is owner-RW only; no group/world bits at all.
        assert _mode(temp_user_data) == 0o600

    def test_rewrite_tightens_loose_mode(self, temp_user_data):
        # Simulate a prior write under default umask that left the file
        # world-readable. The next write must tighten it back to 0o600
        # rather than preserve the loose mode.
        temp_user_data.write_text(json.dumps({}))
        os.chmod(temp_user_data, 0o644)

        github_copilot.write_github_access_token("ghp_test_token")

        assert _mode(temp_user_data) == 0o600

    def test_delete_preserves_0o600(self, temp_user_data):
        # `delete_stored_github_access_token` rewrites the file with the
        # token field removed. The file mode must stay tight even
        # through deletes.
        github_copilot.write_github_access_token("ghp_test_token")
        # Loosen explicitly to verify the delete-write tightens again.
        os.chmod(temp_user_data, 0o644)

        github_copilot.delete_stored_github_access_token()

        assert _mode(temp_user_data) == 0o600

    def test_write_persists_token_payload(self, temp_user_data):
        # Sanity: the mode-tightening fix must not regress the actual
        # token write. The encrypted token must still be present and
        # decryptable on the next read.
        github_copilot.write_github_access_token("ghp_test_token")

        recovered = github_copilot.read_stored_github_access_token()
        assert recovered == "ghp_test_token"
