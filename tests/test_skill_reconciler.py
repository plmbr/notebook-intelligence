import threading
import time
from unittest.mock import patch

import pytest

from notebook_intelligence.skill_manager import SkillManager
from notebook_intelligence.skill_reconciler import SkillReconciler
from notebook_intelligence.skillset import SKILL_ENTRY_FILE, Skill, serialize_skill_md
from tests.conftest import build_tarball


@pytest.fixture
def skill_dirs(tmp_path):
    user_dir = tmp_path / "user_skills"
    project_dir = tmp_path / "project_skills"
    user_dir.mkdir()
    project_dir.mkdir()
    return user_dir, project_dir


@pytest.fixture
def manager(skill_dirs):
    user_dir, project_dir = skill_dirs
    return SkillManager(user_dir, project_dir)


def _write_manifest(tmp_path, entries_yaml):
    p = tmp_path / "manifest.yaml"
    body = f"skills:\n{entries_yaml}" if entries_yaml else "skills: []\n"
    p.write_text(body, encoding="utf-8")
    return str(p)


def _patch_tarball(tar: bytes):
    return patch(
        "notebook_intelligence.skill_github_import._fetch_tarball",
        return_value=tar,
    )


def _patch_sha(sha):
    return patch(
        "notebook_intelligence.skill_reconciler.get_latest_commit_sha",
        return_value=sha,
    )


class TestReconcileInstall:
    def test_installs_missing_managed_skill(self, manager, tmp_path, skill_dirs):
        user_dir, _ = skill_dirs
        manifest = _write_manifest(
            tmp_path,
            "  - url: https://github.com/org/repo/tree/main/alpha\n",
        )
        tar = build_tarball({
            "repo-xyz/alpha/SKILL.md": "---\nname: alpha\ndescription: a\n---\nbody",
        })
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)

        with _patch_sha("abc123"), _patch_tarball(tar):
            result = reconciler.reconcile()

        assert result.added == 1
        assert result.updated == 0
        assert result.removed == 0
        assert result.errors == []
        skill = Skill.from_path(user_dir / "alpha", "user")
        assert skill.managed is True
        assert skill.managed_ref == "abc123"
        assert skill.managed_source == "https://github.com/org/repo/tree/main/alpha"

    def test_skips_when_sha_matches(self, manager, tmp_path, skill_dirs):
        user_dir, _ = skill_dirs
        manifest = _write_manifest(
            tmp_path,
            "  - url: https://github.com/org/repo/tree/main/alpha\n",
        )
        # Pre-install a managed skill with a known SHA.
        bundle = user_dir / "alpha"
        bundle.mkdir()
        (bundle / SKILL_ENTRY_FILE).write_text(
            serialize_skill_md(
                "alpha", "a", [], "body",
                managed_source="https://github.com/org/repo/tree/main/alpha",
                managed_ref="sha_match",
            ),
            encoding="utf-8",
        )
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)

        with _patch_sha("sha_match"), patch(
            "notebook_intelligence.skill_github_import._fetch_tarball"
        ) as fetch:
            result = reconciler.reconcile()

        assert result.unchanged == 1
        assert result.updated == 0
        # Crucial: tarball never fetched when SHA matches.
        fetch.assert_not_called()

    def test_updates_when_sha_differs(self, manager, tmp_path, skill_dirs):
        user_dir, _ = skill_dirs
        manifest = _write_manifest(
            tmp_path,
            "  - url: https://github.com/org/repo/tree/main/alpha\n",
        )
        bundle = user_dir / "alpha"
        bundle.mkdir()
        (bundle / SKILL_ENTRY_FILE).write_text(
            serialize_skill_md(
                "alpha", "old", [], "old body",
                managed_source="https://github.com/org/repo/tree/main/alpha",
                managed_ref="sha_old",
            ),
            encoding="utf-8",
        )
        tar = build_tarball({
            "repo-xyz/alpha/SKILL.md": "---\nname: alpha\ndescription: new\n---\nnew body",
        })
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)

        with _patch_sha("sha_new"), _patch_tarball(tar):
            result = reconciler.reconcile()

        assert result.updated == 1
        reloaded = Skill.from_path(bundle, "user")
        assert reloaded.description == "new"
        assert reloaded.managed_ref == "sha_new"

    def test_full_sha_in_url_skips_probe(self, manager, tmp_path):
        full_sha = "a" * 40
        manifest = _write_manifest(
            tmp_path,
            f"  - url: https://github.com/org/repo/tree/{full_sha}/alpha\n",
        )
        tar = build_tarball({
            "repo-xyz/alpha/SKILL.md": "---\nname: alpha\ndescription: a\n---\nbody",
        })
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)

        with _patch_tarball(tar), patch(
            "notebook_intelligence.skill_reconciler.get_latest_commit_sha"
        ) as probe:
            result = reconciler.reconcile()

        probe.assert_not_called()
        assert result.added == 1


class TestReconcileDelete:
    def test_removes_managed_skill_missing_from_manifest(
        self, manager, tmp_path, skill_dirs
    ):
        user_dir, _ = skill_dirs
        bundle = user_dir / "gone"
        bundle.mkdir()
        (bundle / SKILL_ENTRY_FILE).write_text(
            serialize_skill_md(
                "gone", "d", [], "b",
                managed_source="https://github.com/org/repo/tree/main/gone",
                managed_ref="sha",
            ),
            encoding="utf-8",
        )
        manifest = _write_manifest(tmp_path, "")  # empty manifest
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)

        result = reconciler.reconcile()

        assert result.removed == 1
        assert not bundle.exists()

    def test_preserves_user_authored_skill(self, manager, tmp_path, skill_dirs):
        user_dir, _ = skill_dirs
        manager.create_skill("user", "mine", "my skill", [], "body")
        manifest = _write_manifest(tmp_path, "")  # empty
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)

        result = reconciler.reconcile()

        assert result.removed == 0
        assert (user_dir / "mine" / SKILL_ENTRY_FILE).exists()


class TestReconcileErrors:
    def test_tarball_error_isolated_per_entry(self, manager, tmp_path, skill_dirs):
        user_dir, _ = skill_dirs
        manifest = _write_manifest(
            tmp_path,
            "  - url: https://github.com/org/repo/tree/main/broken\n"
            "  - url: https://github.com/org/repo/tree/main/good\n",
        )
        tar_good = build_tarball({
            "repo-xyz/good/SKILL.md": "---\nname: good\ndescription: g\n---\nbody",
        })

        call_count = {"n": 0}

        def fake_fetch(owner, repo, ref, *, token=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ValueError("network flake")
            return tar_good

        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)
        with _patch_sha("sha"), patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            side_effect=fake_fetch,
        ):
            result = reconciler.reconcile()

        assert result.added == 1  # second entry still installed
        assert len(result.errors) == 1
        assert "network flake" in result.errors[0]
        assert (user_dir / "good" / SKILL_ENTRY_FILE).exists()

    def test_malformed_manifest_logs_and_skips_removals(
        self, manager, tmp_path, skill_dirs
    ):
        user_dir, _ = skill_dirs
        bundle = user_dir / "prev"
        bundle.mkdir()
        (bundle / SKILL_ENTRY_FILE).write_text(
            serialize_skill_md(
                "prev", "d", [], "b",
                managed_source="https://github.com/org/repo/tree/main/prev",
                managed_ref="sha",
            ),
            encoding="utf-8",
        )
        # Malformed — missing required `skills:` list.
        bad = tmp_path / "m.yaml"
        bad.write_text("other: []\n", encoding="utf-8")
        reconciler = SkillReconciler(manager, str(bad), interval_seconds=60)

        result = reconciler.reconcile()

        assert len(result.errors) == 1
        assert result.removed == 0
        # Managed skill left in place — safer than mass-deleting on transient error.
        assert bundle.exists()

    def test_commits_api_error_keeps_existing_install(
        self, manager, tmp_path, skill_dirs
    ):
        user_dir, _ = skill_dirs
        bundle = user_dir / "alpha"
        bundle.mkdir()
        (bundle / SKILL_ENTRY_FILE).write_text(
            serialize_skill_md(
                "alpha", "old", [], "old",
                managed_source="https://github.com/org/repo/tree/main/alpha",
                managed_ref="sha_old",
            ),
            encoding="utf-8",
        )
        manifest = _write_manifest(
            tmp_path,
            "  - url: https://github.com/org/repo/tree/main/alpha\n",
        )
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)

        with _patch_sha(None), patch(
            "notebook_intelligence.skill_github_import._fetch_tarball"
        ) as fetch:
            result = reconciler.reconcile()

        # Probe failed but the skill is already installed — don't re-download;
        # wait for a later cycle that produces a concrete SHA.
        assert result.unchanged == 1
        assert result.updated == 0
        fetch.assert_not_called()
        reloaded = Skill.from_path(bundle, "user")
        assert reloaded.description == "old"
        assert reloaded.managed_ref == "sha_old"

    def test_name_collision_with_user_skill_reports_error(
        self, manager, tmp_path, skill_dirs
    ):
        user_dir, _ = skill_dirs
        manager.create_skill("user", "alpha", "user bundle", [], "mine")
        manifest = _write_manifest(
            tmp_path,
            "  - url: https://github.com/org/repo/tree/main/alpha\n",
        )
        tar = build_tarball({
            "repo-xyz/alpha/SKILL.md": "---\nname: alpha\ndescription: gh\n---\nb",
        })
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)

        with _patch_sha("sha"), _patch_tarball(tar):
            result = reconciler.reconcile()

        assert result.added == 0
        assert any("user-authored" in e for e in result.errors)
        # User skill untouched.
        assert Skill.from_path(user_dir / "alpha", "user").body.strip() == "mine"


class TestManagedToken:
    def test_managed_token_threaded_to_tarball_and_probe(
        self, manager, tmp_path, skill_dirs
    ):
        user_dir, _ = skill_dirs
        manifest = _write_manifest(
            tmp_path,
            "  - url: https://github.com/org/repo/tree/main/alpha\n",
        )
        tar = build_tarball({
            "repo-xyz/alpha/SKILL.md": "---\nname: alpha\ndescription: a\n---\nbody",
        })
        reconciler = SkillReconciler(
            manager, manifest, interval_seconds=60, managed_token="scoped-org-token"
        )

        with patch(
            "notebook_intelligence.skill_reconciler.get_latest_commit_sha",
            return_value="abc123",
        ) as probe, patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            return_value=tar,
        ) as fetch:
            reconciler.reconcile()

        # Probe and tarball fetch both see the scoped managed token, not the
        # user's GITHUB_TOKEN chain.
        assert probe.call_args.kwargs.get("token") == "scoped-org-token"
        assert fetch.call_args.kwargs.get("token") == "scoped-org-token"

    def test_managed_token_failure_is_not_retried_with_fallback(
        self, manager, tmp_path, skill_dirs
    ):
        """Option A: if the deployment's scoped token is rejected by GitHub, the
        error surfaces — we don't silently retry with the user's GITHUB_TOKEN.
        Hiding a misconfigured scoped token would let admins miss expirations.
        """
        manifest = _write_manifest(
            tmp_path,
            "  - url: https://github.com/org/repo/tree/main/alpha\n",
        )
        call_count = {"n": 0}

        def fake_fetch(owner, repo, ref, *, token=None):
            call_count["n"] += 1
            raise ValueError("GitHub rejected the token (HTTP 401)")

        reconciler = SkillReconciler(
            manager, manifest, interval_seconds=60, managed_token="expired-token"
        )
        with _patch_sha("abc123"), patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            side_effect=fake_fetch,
        ):
            result = reconciler.reconcile()

        # Single attempt, error surfaced — no silent retry.
        assert call_count["n"] == 1
        assert result.added == 0
        assert any("rejected the token" in e for e in result.errors)


class TestBackgroundThread:
    def test_runs_once_at_start_and_on_interval(self, manager, tmp_path):
        manifest = _write_manifest(tmp_path, "")
        reconciler = SkillReconciler(manager, manifest, interval_seconds=1)
        call_times = []

        orig_reconcile = reconciler.reconcile

        def tracking_reconcile():
            call_times.append(time.monotonic())
            return orig_reconcile()

        reconciler.reconcile = tracking_reconcile  # type: ignore[assignment]
        # Tight interval for the test.
        reconciler._interval_seconds = 0.05

        reconciler.start()
        try:
            # Wait for at least two passes.
            deadline = time.monotonic() + 2.0
            while len(call_times) < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            reconciler.stop()

        assert len(call_times) >= 2

    def test_stop_is_idempotent(self, manager, tmp_path):
        manifest = _write_manifest(tmp_path, "")
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)
        reconciler.stop()
        reconciler.stop()

    def test_is_running_reflects_thread_state(self, manager, tmp_path):
        manifest = _write_manifest(tmp_path, "")
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)
        assert reconciler.is_running() is False
        reconciler.start()
        try:
            # The thread starts in the constructor's stop-check window; allow
            # a brief beat for it to actually enter _run_loop.
            deadline = time.monotonic() + 1.0
            while not reconciler.is_running() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert reconciler.is_running() is True
        finally:
            reconciler.stop()
        assert reconciler.is_running() is False


class TestPolicyForceOffStop:
    """The reconciler self-stops when NBI_SKILLS_MANAGEMENT_POLICY flips to
    force-off at runtime, so an admin who can update pod env in place has a
    working kill switch without restarting the server (companion to the
    HTTP stop endpoint).
    """

    def test_force_off_at_start_stops_immediately(self, manager, tmp_path, monkeypatch):
        manifest = _write_manifest(tmp_path, "")
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)
        call_count = {"n": 0}
        orig_reconcile = reconciler.reconcile

        def tracking_reconcile():
            call_count["n"] += 1
            return orig_reconcile()

        reconciler.reconcile = tracking_reconcile  # type: ignore[assignment]
        monkeypatch.setenv("NBI_SKILLS_MANAGEMENT_POLICY", "force-off")
        reconciler._interval_seconds = 0.05
        reconciler.start()
        try:
            deadline = time.monotonic() + 2.0
            while reconciler.is_running() and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            reconciler.stop()
        # The loop checks the env BEFORE the reconcile call, so no pass
        # should have run.
        assert call_count["n"] == 0
        assert reconciler.is_running() is False

    def test_force_off_mid_loop_stops_before_next_pass(self, manager, tmp_path, monkeypatch):
        manifest = _write_manifest(tmp_path, "")
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)
        call_count = {"n": 0}
        orig_reconcile = reconciler.reconcile

        def tracking_reconcile():
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Flip the policy after the first pass; the next iteration
                # of the loop should see force-off and stop.
                monkeypatch.setenv("NBI_SKILLS_MANAGEMENT_POLICY", "force-off")
            return orig_reconcile()

        reconciler.reconcile = tracking_reconcile  # type: ignore[assignment]
        reconciler._interval_seconds = 0.05
        reconciler.start()
        try:
            deadline = time.monotonic() + 2.0
            while reconciler.is_running() and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            reconciler.stop()
        # Exactly one reconcile pass should have run before the kill switch
        # took effect on the next iteration.
        assert call_count["n"] == 1
        assert reconciler.is_running() is False

    def test_user_choice_keeps_running(self, manager, tmp_path, monkeypatch):
        manifest = _write_manifest(tmp_path, "")
        reconciler = SkillReconciler(manager, manifest, interval_seconds=60)
        call_count = {"n": 0}
        orig_reconcile = reconciler.reconcile

        def tracking_reconcile():
            call_count["n"] += 1
            return orig_reconcile()

        reconciler.reconcile = tracking_reconcile  # type: ignore[assignment]
        # Explicitly user-choice (default state, but pin it in case test
        # ordering inherits force-off from a sibling test).
        monkeypatch.setenv("NBI_SKILLS_MANAGEMENT_POLICY", "user-choice")
        reconciler._interval_seconds = 0.05
        reconciler.start()
        try:
            deadline = time.monotonic() + 2.0
            while call_count["n"] < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            reconciler.stop()
        # The loop ran at least twice and was not killed by env state.
        assert call_count["n"] >= 2

    def test_policy_check_is_case_insensitive_and_trimmed(self, monkeypatch):
        # Pin the exact env-parsing contract so a future refactor that
        # tightens the match doesn't silently make admin-style "Force-Off"
        # values stop firing the kill switch.
        for env_value, expected in [
            ("force-off", True),
            ("Force-Off", True),
            ("  force-off ", True),
            ("FORCE-OFF", True),
            ("user-choice", False),
            ("", False),
            ("force_off", False),  # underscore is a typo, not a match
        ]:
            monkeypatch.setenv("NBI_SKILLS_MANAGEMENT_POLICY", env_value)
            assert SkillReconciler._policy_force_off() is expected, env_value
