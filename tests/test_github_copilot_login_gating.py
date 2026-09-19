# A Claude-only deployment logged into GitHub Copilot at startup, refreshed the
# token, and polled api.github.com for the life of the server, because the gate
# read the configured provider fields and both of them default to Copilot.
import pytest

from notebook_intelligence.ai_service_manager import (
    github_copilot_serves_a_request,
)

COPILOT = "github-copilot"


def serves(
    agent_mode=None,
    chat="github-copilot",
    inline="github-copilot",
    claude_inline="",
):
    return github_copilot_serves_a_request(agent_mode, chat, inline, claude_inline)


class TestNoAgentMode:
    def test_copilot_chat_needs_a_login(self):
        assert serves(chat=COPILOT, inline="ollama") is True

    def test_copilot_autocomplete_needs_a_login(self):
        assert serves(chat="ollama", inline=COPILOT) is True

    def test_neither_surface_on_copilot_needs_nothing(self):
        assert serves(chat="ollama", inline="ollama") is False


class TestClaudeMode:
    def test_the_defaults_no_longer_log_in(self):
        # The reported case: Claude mode enabled, General tab never touched, so
        # both providers still read github-copilot and the Claude inline
        # setting is unset, which resolves to a Claude model.
        assert serves(agent_mode="claude") is False

    def test_chat_model_is_irrelevant_because_claude_serves_chat(self):
        assert serves(agent_mode="claude", chat=COPILOT, inline="ollama") is False

    def test_inheriting_autocomplete_still_needs_a_login(self):
        # The case a blunt "an agent mode is on, skip Copilot" would break:
        # Claude chat with Copilot autocomplete is a supported combination.
        assert (
            serves(agent_mode="claude", inline=COPILOT, claude_inline="inherit")
            is True
        )

    def test_inheriting_a_non_copilot_provider_does_not(self):
        assert (
            serves(agent_mode="claude", inline="ollama", claude_inline="inherit")
            is False
        )

    @pytest.mark.parametrize("setting", ["", "none", "claude-haiku-4-5"])
    def test_any_non_inherit_setting_means_copilot_is_not_needed(self, setting):
        assert (
            serves(agent_mode="claude", inline=COPILOT, claude_inline=setting)
            is False
        )


class TestAcpMode:
    def test_acp_leaves_autocomplete_to_the_configured_provider(self):
        # ACP swaps the chat participant and nothing else, so Copilot still
        # serves autocomplete when it is the configured provider.
        assert serves(agent_mode="acp", inline=COPILOT) is True

    def test_acp_chat_does_not_use_the_chat_model(self):
        assert serves(agent_mode="acp", chat=COPILOT, inline="ollama") is False

    def test_the_claude_setting_is_ignored_outside_claude_mode(self):
        assert (
            serves(agent_mode="acp", inline=COPILOT, claude_inline="none") is True
        )


@pytest.fixture
def restore_github_copilot_globals():
    """These tests drive module-level auth state, so put it back afterwards.

    Leaving it dirty would make unrelated tests depend on collection order.
    """
    from notebook_intelligence import github_copilot

    saved = (
        github_copilot.github_auth.get('status'),
        github_copilot.github_access_token_provided,
        github_copilot.remember_github_access_token,
    )
    try:
        yield github_copilot
    finally:
        github_copilot.github_auth['status'] = saved[0]
        github_copilot.github_access_token_provided = saved[1]
        github_copilot.remember_github_access_token = saved[2]


class TestStoredTokenHandling:
    """`allow_login=False` must not become "skip everything"."""

    def _reset(self, github_copilot, monkeypatch, deleted=None):
        monkeypatch.setattr(
            github_copilot, 'delete_stored_github_access_token',
            lambda: (deleted if deleted is not None else []).append(True)
        )
        monkeypatch.setattr(
            github_copilot, 'read_stored_github_access_token', lambda: 'gho_test'
        )
        monkeypatch.setattr(
            github_copilot, 'login',
            lambda: (_ for _ in ()).throw(AssertionError('logged in'))
        )
        github_copilot.github_auth['status'] = github_copilot.LoginStatus.NOT_LOGGED_IN
        github_copilot.github_access_token_provided = None

    def test_remember_login_off_still_deletes_the_token(
        self, monkeypatch, restore_github_copilot_globals
    ):
        # Skipping the login must not skip honouring "do not remember me";
        # otherwise the token stays on disk in exactly the deployments that
        # never use Copilot.
        github_copilot = restore_github_copilot_globals

        deleted = []
        self._reset(github_copilot, monkeypatch, deleted)

        github_copilot.login_with_existing_credentials(False, allow_login=False)

        assert deleted == [True]

    def test_no_login_happens_when_copilot_serves_nothing(self, monkeypatch, restore_github_copilot_globals):
        github_copilot = restore_github_copilot_globals

        self._reset(github_copilot, monkeypatch)

        # `login` raises if called; the assertion below is the positive
        # evidence that the gate short-circuited rather than the call simply
        # being renamed out from under the patch.
        github_copilot.login_with_existing_credentials(True, allow_login=False)

        assert github_copilot.github_access_token_provided is None

    def test_the_stored_token_is_not_even_read(self, monkeypatch, restore_github_copilot_globals):
        # Reading it warns about the token password, which is the line users
        # report seeing in deployments that never touch Copilot.
        github_copilot = restore_github_copilot_globals

        self._reset(github_copilot, monkeypatch)
        reads = []
        monkeypatch.setattr(
            github_copilot, 'read_stored_github_access_token',
            lambda: reads.append(True) or 'gho_test'
        )

        github_copilot.login_with_existing_credentials(True, allow_login=False)

        assert reads == []

    def test_the_remember_preference_is_recorded_even_when_login_is_skipped(self, monkeypatch, restore_github_copilot_globals):
        # `remember_github_access_token` used to be set as a side effect of
        # reading the token. Skipping the read must not silently turn off
        # "remember login" for a login started from Settings afterwards.
        github_copilot = restore_github_copilot_globals

        self._reset(github_copilot, monkeypatch)
        github_copilot.remember_github_access_token = False

        github_copilot.login_with_existing_credentials(True, allow_login=False)

        assert github_copilot.remember_github_access_token is True

    def test_login_still_happens_when_copilot_serves_a_request(self, monkeypatch, restore_github_copilot_globals):
        github_copilot = restore_github_copilot_globals

        self._reset(github_copilot, monkeypatch)
        calls = []
        monkeypatch.setattr(github_copilot, 'login', lambda: calls.append(True))
        monkeypatch.setattr(github_copilot.os.path, 'exists', lambda _p: False)

        github_copilot.login_with_existing_credentials(True, allow_login=True)

        assert calls == [True]


class TestManualSignIn:
    """Startup no longer reads the stored token, so `login()` has to."""

    def test_signing_in_reuses_a_stored_token_instead_of_a_device_code(
        self, monkeypatch, restore_github_copilot_globals
    ):
        # The Settings button calls login() directly. Without the read there,
        # a user in Claude mode with a perfectly good stored token would be
        # sent through github.com/login/device for nothing.
        github_copilot = restore_github_copilot_globals

        github_copilot.github_access_token_provided = None
        github_copilot.remember_github_access_token = True
        monkeypatch.setattr(
            github_copilot, 'read_stored_github_access_token', lambda: 'gho_stored'
        )
        monkeypatch.setattr(
            github_copilot, 'get_device_verification_info', lambda: None
        )

        github_copilot.login()

        assert github_copilot.github_access_token_provided == 'gho_stored'

    def test_signing_in_does_not_read_a_token_the_user_asked_not_to_keep(
        self, monkeypatch, restore_github_copilot_globals
    ):
        github_copilot = restore_github_copilot_globals

        github_copilot.github_access_token_provided = None
        github_copilot.remember_github_access_token = False
        reads = []
        monkeypatch.setattr(
            github_copilot, 'read_stored_github_access_token',
            lambda: reads.append(True) or 'gho_stored'
        )
        monkeypatch.setattr(
            github_copilot, 'get_device_verification_info', lambda: None
        )

        github_copilot.login()

        assert reads == []
        assert github_copilot.github_access_token_provided is None
