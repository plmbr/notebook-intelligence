import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

import notebook_intelligence.extension as ext_module
from notebook_intelligence.extension import (
    SkillBundleFileHandler,
    SkillBundleFileRenameHandler,
    SkillDetailHandler,
    SkillRenameHandler,
    SkillsBaseHandler,
    SkillsContextHandler,
    SkillsImportHandler,
    SkillsImportPreviewHandler,
    SkillsListHandler,
    SkillsReconcileHandler,
    SkillsReconcilerStopHandler,
    SkillsSyncAllTrackingHandler,
    SkillSyncHandler,
)
from notebook_intelligence.skill_reconciler import ReconcileResult
from notebook_intelligence.skill_manager import SkillManager
from notebook_intelligence.skillset import SKILL_ENTRY_FILE
from tests.conftest import build_tarball


@pytest.fixture
def skill_manager(tmp_path):
    user_dir = tmp_path / "user"
    project_dir = tmp_path / "project"
    user_dir.mkdir()
    project_dir.mkdir()
    manager = SkillManager(user_dir, project_dir)
    with patch.object(ext_module, "ai_service_manager") as mock_asm:
        mock_asm.get_skill_manager.return_value = manager
        yield manager


def _make_handler(handler_cls, body: bytes = b"", query_args: dict | None = None):
    handler = MagicMock(spec=handler_cls)
    handler.request = MagicMock()
    handler.request.body = body
    query_args = query_args or {}

    def get_query_argument(name, default=None):
        return query_args.get(name, default)

    handler.get_query_argument = get_query_argument
    # The `skill_manager` property on SkillsBaseHandler is shadowed by the spec'd mock,
    # so resolve it explicitly via the patched ai_service_manager.
    handler.skill_manager = ext_module.ai_service_manager.get_skill_manager()
    # Bind real helper implementations so handler logic exercises actual code paths.
    handler._parse_json_body = lambda: SkillsBaseHandler._parse_json_body(handler)
    handler._bundle_rel_path = lambda: SkillsBaseHandler._bundle_rel_path(handler)
    handler._error = lambda exc: SkillsBaseHandler._error(handler, exc)
    handler._reject_if_github_import_disabled = (
        lambda: SkillsBaseHandler._reject_if_github_import_disabled(handler)
    )
    handler.allow_github_skill_import = SkillsBaseHandler.allow_github_skill_import
    # `_error` reads the real dict, not the spec'd mock proxy.
    handler.exception_status_map = SkillsBaseHandler.exception_status_map
    # Bind real class attributes from the handler so MagicMock auto-proxies
    # don't return MagicMock placeholders when handler code reads them
    # (e.g. SkillsSyncAllTrackingHandler.SYNC_CONCURRENCY).
    for attr in ("SYNC_CONCURRENCY",):
        if hasattr(handler_cls, attr):
            setattr(handler, attr, getattr(handler_cls, attr))
    return handler


def _parse_response(handler) -> dict:
    return json.loads(handler.finish.call_args[0][0])


class TestSkillsListHandler:
    def test_list_empty(self, skill_manager):
        handler = _make_handler(SkillsListHandler)
        SkillsListHandler.get(handler)
        body = _parse_response(handler)
        assert body == {"skills": []}

    def test_list_includes_both_scopes(self, skill_manager):
        skill_manager.create_skill("user", "u-skill", "d", [], "")
        skill_manager.create_skill("project", "p-skill", "d", [], "")
        handler = _make_handler(SkillsListHandler)
        SkillsListHandler.get(handler)
        body = _parse_response(handler)
        names = {(s["name"], s["scope"]) for s in body["skills"]}
        assert names == {("u-skill", "user"), ("p-skill", "project")}


class TestSkillsCreate:
    def test_create_skill(self, skill_manager):
        handler = _make_handler(
            SkillsListHandler,
            body=json.dumps({
                "scope": "user",
                "name": "new-skill",
                "description": "d",
                "allowed_tools": ["Read"],
                "body": "# body",
            }).encode(),
        )
        SkillsListHandler.post(handler)
        body = _parse_response(handler)
        assert body["skill"]["name"] == "new-skill"
        assert body["skill"]["allowed_tools"] == ["Read"]
        assert "# body" in body["skill"]["body"]

    def test_create_rejects_invalid_name(self, skill_manager):
        handler = _make_handler(
            SkillsListHandler,
            body=json.dumps({"scope": "user", "name": "UPPER"}).encode(),
        )
        SkillsListHandler.post(handler)
        handler.set_status.assert_called_with(400)
        body = _parse_response(handler)
        assert "Invalid skill name" in body["error"]

    def test_create_rejects_duplicate(self, skill_manager):
        skill_manager.create_skill("user", "dup", "d", [], "")
        handler = _make_handler(
            SkillsListHandler,
            body=json.dumps({"scope": "user", "name": "dup"}).encode(),
        )
        SkillsListHandler.post(handler)
        handler.set_status.assert_called_with(400)


class TestSkillDetail:
    def test_get_existing(self, skill_manager):
        skill_manager.create_skill("user", "x", "desc", ["Read"], "body")
        handler = _make_handler(SkillDetailHandler)
        SkillDetailHandler.get(handler, "user", "x")
        body = _parse_response(handler)
        assert body["skill"]["name"] == "x"
        assert body["skill"]["allowed_tools"] == ["Read"]
        assert "body" in body["skill"]["body"]

    def test_get_missing_returns_404(self, skill_manager):
        handler = _make_handler(SkillDetailHandler)
        SkillDetailHandler.get(handler, "user", "nope")
        handler.set_status.assert_called_with(404)

    def test_update_persists_changes(self, skill_manager):
        skill_manager.create_skill("user", "x", "old", [], "body")
        handler = _make_handler(
            SkillDetailHandler,
            body=json.dumps({"description": "new"}).encode(),
        )
        SkillDetailHandler.put(handler, "user", "x")
        body = _parse_response(handler)
        assert body["skill"]["description"] == "new"

    def test_put_tracks_upstream_on_managed_returns_400(self, skill_manager):
        # The manager raises ValueError for managed + tracking; the handler
        # must map that to 400 rather than letting it bubble as a 500.
        user_dir = skill_manager.scope_dir("user")
        bundle = user_dir / "m"
        bundle.mkdir()
        (bundle / SKILL_ENTRY_FILE).write_text(
            "---\nname: m\ndescription: d\n"
            "managed_source: https://github.com/org/repo\n"
            "managed_ref: sha\n---\nbody",
            encoding="utf-8",
        )
        handler = _make_handler(
            SkillDetailHandler,
            body=json.dumps({"tracks_upstream": True}).encode(),
        )
        SkillDetailHandler.put(handler, "user", "m")
        handler.set_status.assert_called_with(400)
        body = _parse_response(handler)
        assert "Managed skills" in body["error"]

    def test_put_tracks_upstream_on_no_source_returns_400(self, skill_manager):
        # A skill with no recorded source URL cannot opt into tracking;
        # the manager raises ValueError and the handler maps to 400.
        skill_manager.create_skill("user", "plain", "d", [], "b")
        handler = _make_handler(
            SkillDetailHandler,
            body=json.dumps({"tracks_upstream": True}).encode(),
        )
        SkillDetailHandler.put(handler, "user", "plain")
        handler.set_status.assert_called_with(400)
        body = _parse_response(handler)
        assert "no recorded source" in body["error"]

    def test_put_tracks_upstream_blocked_when_github_import_disabled(
        self, skill_manager
    ):
        # The toggle would let an admin's "imports disabled" kill switch
        # leak: bit gets set, sync still blocked. Reject the toggle when
        # the policy is off.
        tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: x\ndescription: d\n---\nb",
        })
        with patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            return_value=tar,
        ):
            skill_manager.import_from_github(
                "https://github.com/owner/repo", scope="user"
            )
        handler = _make_handler(
            SkillDetailHandler,
            body=json.dumps({"tracks_upstream": True}).encode(),
        )
        handler.allow_github_skill_import = False
        SkillDetailHandler.put(handler, "user", "x")
        handler.set_status.assert_called_with(403)

    def test_put_without_tracks_upstream_preserves_current(self, skill_manager):
        # Regression pin: a PUT body that omits `tracks_upstream` must NOT
        # silently flip the bit off. The handler passes None for that field
        # and the manager treats None as "leave unchanged."
        tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: x\ndescription: d\n---\nb",
        })
        with patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            return_value=tar,
        ):
            skill_manager.import_from_github(
                "https://github.com/owner/repo",
                scope="user",
                tracks_upstream=True,
            )
        handler = _make_handler(
            SkillDetailHandler,
            body=json.dumps({"description": "new"}).encode(),
        )
        SkillDetailHandler.put(handler, "user", "x")
        body = _parse_response(handler)
        assert body["skill"]["description"] == "new"
        assert body["skill"]["tracks_upstream"] is True

    def test_update_can_toggle_tracks_upstream(self, skill_manager):
        # Bootstrap a user-imported skill that has a source but isn't
        # tracking yet. PUT with tracks_upstream=true flips it on.
        tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: x\ndescription: d\n---\nbody",
        })
        with patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            return_value=tar,
        ):
            skill_manager.import_from_github(
                "https://github.com/owner/repo", scope="user"
            )
        handler = _make_handler(
            SkillDetailHandler,
            body=json.dumps({"tracks_upstream": True}).encode(),
        )
        SkillDetailHandler.put(handler, "user", "x")
        body = _parse_response(handler)
        assert body["skill"]["tracks_upstream"] is True

    def test_update_missing_returns_404(self, skill_manager):
        handler = _make_handler(
            SkillDetailHandler,
            body=json.dumps({"description": "new"}).encode(),
        )
        SkillDetailHandler.put(handler, "user", "nope")
        handler.set_status.assert_called_with(404)

    def test_delete_removes_skill(self, skill_manager):
        skill_manager.create_skill("user", "gone", "d", [], "")
        handler = _make_handler(SkillDetailHandler)
        SkillDetailHandler.delete(handler, "user", "gone")
        body = _parse_response(handler)
        assert body["success"] is True
        assert skill_manager.get_skill("user", "gone") is None

    def test_delete_missing_returns_404(self, skill_manager):
        handler = _make_handler(SkillDetailHandler)
        SkillDetailHandler.delete(handler, "user", "nope")
        handler.set_status.assert_called_with(404)


class TestSkillRenameHandler:
    def test_rename_success(self, skill_manager):
        skill_manager.create_skill("user", "old", "d", [], "body")
        handler = _make_handler(
            SkillRenameHandler, body=json.dumps({"new_name": "new"}).encode()
        )
        SkillRenameHandler.post(handler, "user", "old")
        body = _parse_response(handler)
        assert body["skill"]["name"] == "new"
        assert skill_manager.get_skill("user", "old") is None

    def test_rename_missing_new_name_returns_400(self, skill_manager):
        skill_manager.create_skill("user", "old", "d", [], "")
        handler = _make_handler(SkillRenameHandler, body=json.dumps({}).encode())
        SkillRenameHandler.post(handler, "user", "old")
        handler.set_status.assert_called_with(400)

    def test_rename_duplicate_returns_409(self, skill_manager):
        skill_manager.create_skill("user", "a", "d", [], "")
        skill_manager.create_skill("user", "b", "d", [], "")
        handler = _make_handler(
            SkillRenameHandler, body=json.dumps({"new_name": "b"}).encode()
        )
        SkillRenameHandler.post(handler, "user", "a")
        handler.set_status.assert_called_with(409)

    def test_rename_missing_source_returns_404(self, skill_manager):
        handler = _make_handler(
            SkillRenameHandler, body=json.dumps({"new_name": "new"}).encode()
        )
        SkillRenameHandler.post(handler, "user", "nope")
        handler.set_status.assert_called_with(404)

    def test_rename_invalid_new_name_returns_400(self, skill_manager):
        skill_manager.create_skill("user", "old", "d", [], "")
        handler = _make_handler(
            SkillRenameHandler, body=json.dumps({"new_name": "UPPER"}).encode()
        )
        SkillRenameHandler.post(handler, "user", "old")
        handler.set_status.assert_called_with(400)


class TestSkillsContextHandler:
    def test_returns_configured_dirs(self, skill_manager, tmp_path, monkeypatch):
        monkeypatch.setattr(ext_module, "get_jupyter_root_dir", lambda: str(tmp_path))
        handler = _make_handler(SkillsContextHandler)
        SkillsContextHandler.get(handler)
        body = _parse_response(handler)
        assert body["project_root"] == str(tmp_path)
        assert body["project_name"] == tmp_path.name
        assert body["user_skills_dir"] == str(skill_manager.scope_dir("user"))
        assert body["project_skills_dir"] == str(skill_manager.scope_dir("project"))


class TestSkillsImportHandlers:
    def test_preview_returns_metadata(self, skill_manager):
        tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: imported\ndescription: d\n---\nbody",
        })
        handler = _make_handler(
            SkillsImportPreviewHandler,
            body=json.dumps({"url": "https://github.com/owner/repo"}).encode(),
        )
        with patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            return_value=tar,
        ):
            SkillsImportPreviewHandler.post(handler)
        body = _parse_response(handler)
        assert body["preview"]["name"] == "imported"
        assert body["preview"]["exists_in_user_scope"] is False

    def test_preview_missing_url_returns_400(self, skill_manager):
        handler = _make_handler(
            SkillsImportPreviewHandler, body=json.dumps({}).encode()
        )
        SkillsImportPreviewHandler.post(handler)
        handler.set_status.assert_called_with(400)

    def test_preview_invalid_url_returns_400(self, skill_manager):
        handler = _make_handler(
            SkillsImportPreviewHandler,
            body=json.dumps({"url": "https://gitlab.com/owner/repo"}).encode(),
        )
        SkillsImportPreviewHandler.post(handler)
        handler.set_status.assert_called_with(400)

    def test_import_installs_skill(self, skill_manager):
        tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: gh-skill\ndescription: d\n---\nhello",
        })
        handler = _make_handler(
            SkillsImportHandler,
            body=json.dumps({
                "url": "https://github.com/owner/repo",
                "scope": "user",
            }).encode(),
        )
        with patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            return_value=tar,
        ):
            SkillsImportHandler.post(handler)
        body = _parse_response(handler)
        assert body["skill"]["name"] == "gh-skill"
        assert body["skill"]["source"] == "https://github.com/owner/repo"

    def test_import_invalid_scope_returns_400(self, skill_manager):
        handler = _make_handler(
            SkillsImportHandler,
            body=json.dumps({
                "url": "https://github.com/owner/repo",
                "scope": "bogus",
            }).encode(),
        )
        SkillsImportHandler.post(handler)
        handler.set_status.assert_called_with(400)

    def test_import_collision_returns_409(self, skill_manager):
        skill_manager.create_skill("user", "dup", "d", [], "")
        tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: dup\ndescription: d\n---\nb",
        })
        handler = _make_handler(
            SkillsImportHandler,
            body=json.dumps({
                "url": "https://github.com/owner/repo",
                "scope": "user",
            }).encode(),
        )
        with patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            return_value=tar,
        ):
            SkillsImportHandler.post(handler)
        handler.set_status.assert_called_with(409)

    def test_preview_returns_403_when_disabled(self, skill_manager):
        handler = _make_handler(
            SkillsImportPreviewHandler,
            body=json.dumps({"url": "https://github.com/owner/repo"}).encode(),
        )
        handler.allow_github_skill_import = False
        SkillsImportPreviewHandler.post(handler)
        handler.set_status.assert_called_with(403)
        body = _parse_response(handler)
        assert "disabled" in body["error"].lower()

    def test_import_returns_403_when_disabled(self, skill_manager):
        handler = _make_handler(
            SkillsImportHandler,
            body=json.dumps({
                "url": "https://github.com/owner/repo",
                "scope": "user",
            }).encode(),
        )
        handler.allow_github_skill_import = False
        SkillsImportHandler.post(handler)
        handler.set_status.assert_called_with(403)

    def test_import_passes_tracks_upstream_flag_through(self, skill_manager):
        tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: tr\ndescription: d\n---\nbody",
        })
        handler = _make_handler(
            SkillsImportHandler,
            body=json.dumps({
                "url": "https://github.com/owner/repo",
                "scope": "user",
                "tracks_upstream": True,
            }).encode(),
        )
        with patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            return_value=tar,
        ):
            SkillsImportHandler.post(handler)
        body = _parse_response(handler)
        assert body["skill"]["tracks_upstream"] is True


class TestSkillSyncHandler:
    """Per-skill sync action: re-fetch bundle, replace on disk, surface
    failures without touching the existing install.
    """

    def _patch_sha(self, sha):
        return patch(
            "notebook_intelligence.skill_github_import.get_latest_commit_sha",
            return_value=sha,
        )

    def _patch_tar(self, tar):
        return patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            return_value=tar,
        )

    def _bootstrap_tracking_skill(self, manager):
        tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: tr\ndescription: old\n---\nold",
        })
        with self._patch_tar(tar):
            manager.import_from_github(
                "https://github.com/owner/repo",
                scope="user",
                tracks_upstream=True,
            )

    def test_sync_updates_when_sha_changes(self, skill_manager):
        self._bootstrap_tracking_skill(skill_manager)
        new_tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: tr\ndescription: new\n---\nnew",
        })
        handler = _make_handler(SkillSyncHandler)
        with self._patch_sha("def4567"), self._patch_tar(new_tar):
            asyncio.run(SkillSyncHandler.post(handler, "user", "tr"))
        body = _parse_response(handler)
        assert body == {"updated": True, "ref": "def4567"}

    def test_sync_unchanged_short_circuits(self, skill_manager):
        self._bootstrap_tracking_skill(skill_manager)
        # First sync stamps the ref. Second sync with same SHA → unchanged.
        new_tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: tr\ndescription: d\n---\nb",
        })
        handler1 = _make_handler(SkillSyncHandler)
        with self._patch_sha("aaa"), self._patch_tar(new_tar):
            asyncio.run(SkillSyncHandler.post(handler1, "user", "tr"))

        handler2 = _make_handler(SkillSyncHandler)
        with self._patch_sha("aaa"), patch(
            "notebook_intelligence.skill_github_import._fetch_tarball"
        ) as fetch:
            asyncio.run(SkillSyncHandler.post(handler2, "user", "tr"))
        body = _parse_response(handler2)
        assert body == {"updated": False, "ref": "aaa"}
        fetch.assert_not_called()

    def test_sync_returns_404_for_missing_skill(self, skill_manager):
        handler = _make_handler(SkillSyncHandler)
        asyncio.run(SkillSyncHandler.post(handler, "user", "ghost"))
        handler.set_status.assert_called_with(404)

    def test_sync_rejects_non_tracking_skill(self, skill_manager):
        skill_manager.create_skill("user", "plain", "d", [], "b")
        handler = _make_handler(SkillSyncHandler)
        asyncio.run(SkillSyncHandler.post(handler, "user", "plain"))
        # ValueError maps to 400 via exception_status_map.
        body = _parse_response(handler)
        assert "not tracking upstream" in body["error"]

    def test_sync_probe_failure_maps_to_502(self, skill_manager):
        # Probe failure raises RuntimeError. The exception_status_map sends
        # that to 502 (upstream unreachable) rather than the default 400
        # (which would mislead the client into thinking the request was
        # malformed).
        self._bootstrap_tracking_skill(skill_manager)
        handler = _make_handler(SkillSyncHandler)
        with self._patch_sha(None):
            asyncio.run(SkillSyncHandler.post(handler, "user", "tr"))
        handler.set_status.assert_called_with(502)

    def test_sync_returns_403_when_github_import_disabled(self, skill_manager):
        self._bootstrap_tracking_skill(skill_manager)
        handler = _make_handler(SkillSyncHandler)
        handler.allow_github_skill_import = False
        asyncio.run(SkillSyncHandler.post(handler, "user", "tr"))
        handler.set_status.assert_called_with(403)


class TestSkillsSyncAllTrackingHandler:
    def _patch_sha(self, sha):
        return patch(
            "notebook_intelligence.skill_github_import.get_latest_commit_sha",
            return_value=sha,
        )

    def _patch_tar(self, tar):
        return patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            return_value=tar,
        )

    def test_sync_all_isolates_per_skill_failures(self, skill_manager):
        # Two tracking skills, one of which will fail to sync.
        tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: alpha\ndescription: d\n---\nb",
        })
        with self._patch_tar(tar):
            skill_manager.import_from_github(
                "https://github.com/owner/alpha-repo",
                scope="user",
                tracks_upstream=True,
            )
        tar2 = build_tarball({
            "repo-x/SKILL.md": "---\nname: beta\ndescription: d\n---\nb",
        })
        with self._patch_tar(tar2):
            skill_manager.import_from_github(
                "https://github.com/owner/beta-repo",
                scope="user",
                tracks_upstream=True,
            )
        # Probe returns SHA for both; tarball for alpha succeeds, beta
        # raises (simulated upstream failure).
        new_tar = build_tarball({
            "repo-x/SKILL.md": "---\nname: alpha\ndescription: new\n---\nnew",
        })
        fetch_calls = {"n": 0}

        def fake_fetch(owner, repo, ref, *, token=None):
            fetch_calls["n"] += 1
            if "beta" in repo:
                raise ValueError("beta upstream offline")
            return new_tar

        handler = _make_handler(SkillsSyncAllTrackingHandler)
        with self._patch_sha("sha1"), patch(
            "notebook_intelligence.skill_github_import._fetch_tarball",
            side_effect=fake_fetch,
        ):
            asyncio.run(SkillsSyncAllTrackingHandler.post(handler))
        body = _parse_response(handler)
        results = {r["name"]: r for r in body["results"]}
        # Alpha synced; beta surfaced an error.
        assert results["alpha"]["updated"] is True
        assert "error" in results["beta"]
        assert "beta upstream offline" in results["beta"]["error"]

    def test_sync_all_with_no_tracking_skills_returns_empty(self, skill_manager):
        skill_manager.create_skill("user", "plain", "d", [], "b")
        handler = _make_handler(SkillsSyncAllTrackingHandler)
        asyncio.run(SkillsSyncAllTrackingHandler.post(handler))
        body = _parse_response(handler)
        assert body == {"results": []}

    def test_sync_all_returns_403_when_github_import_disabled(
        self, skill_manager
    ):
        handler = _make_handler(SkillsSyncAllTrackingHandler)
        handler.allow_github_skill_import = False
        asyncio.run(SkillsSyncAllTrackingHandler.post(handler))
        handler.set_status.assert_called_with(403)


class TestResolveBoolWithEnv:
    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "On"])
    def test_truthy_env_overrides_false_traitlet(self, value):
        with patch.dict("os.environ", {"NBI_TEST_FLAG": value}):
            assert ext_module._resolve_bool_with_env("NBI_TEST_FLAG", False) is True

    @pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "Off"])
    def test_falsy_env_overrides_true_traitlet(self, value):
        with patch.dict("os.environ", {"NBI_TEST_FLAG": value}):
            assert ext_module._resolve_bool_with_env("NBI_TEST_FLAG", True) is False

    def test_unset_env_returns_traitlet(self, monkeypatch):
        monkeypatch.delenv("NBI_TEST_FLAG", raising=False)
        assert ext_module._resolve_bool_with_env("NBI_TEST_FLAG", True) is True
        assert ext_module._resolve_bool_with_env("NBI_TEST_FLAG", False) is False

    def test_invalid_env_raises(self):
        with patch.dict("os.environ", {"NBI_TEST_FLAG": "maybe"}):
            with pytest.raises(ValueError, match="NBI_TEST_FLAG"):
                ext_module._resolve_bool_with_env("NBI_TEST_FLAG", True)

    def test_none_fallback_is_treated_as_false(self, monkeypatch):
        monkeypatch.delenv("NBI_TEST_FLAG", raising=False)
        assert ext_module._resolve_bool_with_env("NBI_TEST_FLAG", None) is False


class TestResolvePositiveIntWithEnv:
    def test_unset_env_returns_traitlet(self, monkeypatch):
        monkeypatch.delenv("NBI_TEST_CAP", raising=False)
        assert ext_module._resolve_positive_int_with_env("NBI_TEST_CAP", 100) == 100

    def test_valid_env_overrides_traitlet(self):
        with patch.dict("os.environ", {"NBI_TEST_CAP": "250"}):
            assert (
                ext_module._resolve_positive_int_with_env("NBI_TEST_CAP", 100) == 250
            )

    def test_invalid_env_warns_and_falls_back(self, caplog):
        with patch.dict("os.environ", {"NBI_TEST_CAP": "huge"}):
            with caplog.at_level("WARNING"):
                result = ext_module._resolve_positive_int_with_env(
                    "NBI_TEST_CAP", 100
                )
        assert result == 100
        assert "Ignoring invalid NBI_TEST_CAP" in caplog.text

    def test_negative_env_clamps_to_zero_with_warning(self, caplog):
        with patch.dict("os.environ", {"NBI_TEST_CAP": "-5"}):
            with caplog.at_level("WARNING"):
                result = ext_module._resolve_positive_int_with_env(
                    "NBI_TEST_CAP", 100
                )
        assert result == 0
        assert "negative" in caplog.text.lower()

    def test_zero_passes_through(self):
        with patch.dict("os.environ", {"NBI_TEST_CAP": "0"}):
            assert ext_module._resolve_positive_int_with_env("NBI_TEST_CAP", 100) == 0


class TestResolveCsvAppended:
    """The csv env-var merge for additive list traitlets (e.g.
    ``additional_skipped_workspace_directories``). Env appends to the
    traitlet rather than overriding so per-pod profiles can layer on
    an org baseline."""

    ENV = "NBI_TEST_CSV"

    def test_env_unset_returns_traitlet_unchanged(self, monkeypatch):
        monkeypatch.delenv(self.ENV, raising=False)
        assert ext_module._resolve_csv_appended(self.ENV, ["foo"]) == ["foo"]

    def test_traitlet_none_with_env_unset_returns_empty(self, monkeypatch):
        monkeypatch.delenv(self.ENV, raising=False)
        assert ext_module._resolve_csv_appended(self.ENV, None) == []

    def test_empty_env_returns_traitlet(self):
        with patch.dict("os.environ", {self.ENV: ""}):
            assert ext_module._resolve_csv_appended(self.ENV, ["foo"]) == ["foo"]

    def test_whitespace_only_env_returns_traitlet(self):
        with patch.dict("os.environ", {self.ENV: "   "}):
            assert ext_module._resolve_csv_appended(self.ENV, ["foo"]) == ["foo"]

    def test_env_strips_whitespace_around_each_token(self):
        with patch.dict("os.environ", {self.ENV: "  build , dist "}):
            assert ext_module._resolve_csv_appended(self.ENV, []) == ["build", "dist"]

    def test_env_filters_empty_segments(self):
        with patch.dict("os.environ", {self.ENV: ",build,,dist,"}):
            assert ext_module._resolve_csv_appended(self.ENV, []) == ["build", "dist"]

    def test_env_appends_to_traitlet(self):
        with patch.dict("os.environ", {self.ENV: "bar"}):
            assert ext_module._resolve_csv_appended(self.ENV, ["foo"]) == ["foo", "bar"]

    def test_dedupes_across_traitlet_and_env_preserving_order(self):
        # Duplicate-across-sources is a common operator typo when an env-var
        # layer is added on top of an existing baseline; the wire payload
        # should stay tidy.
        with patch.dict("os.environ", {self.ENV: "build,dist,build"}):
            assert ext_module._resolve_csv_appended(
                self.ENV, ["build", "foo"]
            ) == ["build", "foo", "dist"]


class TestResolvePolicyWithEnv:
    """``_resolve_policy_with_env`` must fail loud on typos so a misspelled
    ``NBI_SKILLS_MANAGEMENT_POLICY=forceoff`` doesn't silently boot with
    the (lax) traitlet default. Matches the contract of
    ``_resolve_bool_with_env``."""

    ENV = "NBI_TEST_POLICY"

    def test_unset_env_returns_traitlet(self, monkeypatch):
        monkeypatch.delenv(self.ENV, raising=False)
        assert (
            ext_module._resolve_policy_with_env(self.ENV, "force-off")
            == "force-off"
        )

    def test_valid_env_overrides_traitlet(self):
        with patch.dict("os.environ", {self.ENV: "force-on"}):
            assert (
                ext_module._resolve_policy_with_env(self.ENV, "force-off")
                == "force-on"
            )

    def test_invalid_env_raises(self):
        with patch.dict("os.environ", {self.ENV: "forceoff"}):
            with pytest.raises(ValueError, match=self.ENV):
                ext_module._resolve_policy_with_env(self.ENV, "user-choice")


class TestSkillBundleFileHandler:
    def test_write_and_read_bundle_file(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        put_handler = _make_handler(
            SkillBundleFileHandler,
            body=json.dumps({"content": "print(1)"}).encode(),
            query_args={"path": "helper.py"},
        )
        SkillBundleFileHandler.put(put_handler, "user", "bun")
        assert _parse_response(put_handler)["success"] is True

        get_handler = _make_handler(SkillBundleFileHandler, query_args={"path": "helper.py"})
        SkillBundleFileHandler.get(get_handler, "user", "bun")
        assert _parse_response(get_handler)["content"] == "print(1)"

    def test_missing_path_param_returns_400(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        handler = _make_handler(SkillBundleFileHandler, query_args={})
        SkillBundleFileHandler.get(handler, "user", "bun")
        handler.set_status.assert_called_with(400)

    def test_path_traversal_rejected(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        handler = _make_handler(
            SkillBundleFileHandler,
            body=json.dumps({"content": "x"}).encode(),
            query_args={"path": "../escape.py"},
        )
        SkillBundleFileHandler.put(handler, "user", "bun")
        handler.set_status.assert_called_with(400)

    def test_absolute_path_rejected(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        handler = _make_handler(
            SkillBundleFileHandler,
            body=json.dumps({"content": "x"}).encode(),
            query_args={"path": "/etc/passwd"},
        )
        SkillBundleFileHandler.put(handler, "user", "bun")
        handler.set_status.assert_called_with(400)

    def test_delete_skill_md_rejected(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        handler = _make_handler(SkillBundleFileHandler, query_args={"path": SKILL_ENTRY_FILE})
        SkillBundleFileHandler.delete(handler, "user", "bun")
        handler.set_status.assert_called_with(400)

    def test_delete_missing_file_returns_404(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        handler = _make_handler(SkillBundleFileHandler, query_args={"path": "missing.py"})
        SkillBundleFileHandler.delete(handler, "user", "bun")
        handler.set_status.assert_called_with(404)


class TestSkillBundleFileRenameHandler:
    def test_rename_success(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        skill_manager.write_bundle_file("user", "bun", "old.txt", "x")
        handler = _make_handler(
            SkillBundleFileRenameHandler,
            body=json.dumps({"from": "old.txt", "to": "new.txt"}).encode(),
        )
        SkillBundleFileRenameHandler.post(handler, "user", "bun")
        assert _parse_response(handler)["success"] is True
        assert skill_manager.read_bundle_file("user", "bun", "new.txt") == "x"

    def test_rename_missing_body_fields_returns_400(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        handler = _make_handler(
            SkillBundleFileRenameHandler, body=json.dumps({"from": "a"}).encode()
        )
        SkillBundleFileRenameHandler.post(handler, "user", "bun")
        handler.set_status.assert_called_with(400)

    def test_rename_to_existing_returns_409(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        skill_manager.write_bundle_file("user", "bun", "a.txt", "x")
        skill_manager.write_bundle_file("user", "bun", "b.txt", "y")
        handler = _make_handler(
            SkillBundleFileRenameHandler,
            body=json.dumps({"from": "a.txt", "to": "b.txt"}).encode(),
        )
        SkillBundleFileRenameHandler.post(handler, "user", "bun")
        handler.set_status.assert_called_with(409)

    def test_rename_skill_md_rejected(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        handler = _make_handler(
            SkillBundleFileRenameHandler,
            body=json.dumps({"from": SKILL_ENTRY_FILE, "to": "x.md"}).encode(),
        )
        SkillBundleFileRenameHandler.post(handler, "user", "bun")
        handler.set_status.assert_called_with(400)

    def test_rename_missing_source_returns_404(self, skill_manager):
        skill_manager.create_skill("user", "bun", "d", [], "")
        handler = _make_handler(
            SkillBundleFileRenameHandler,
            body=json.dumps({"from": "nope.txt", "to": "yep.txt"}).encode(),
        )
        SkillBundleFileRenameHandler.post(handler, "user", "bun")
        handler.set_status.assert_called_with(404)


class TestSkillsReconcileHandler:
    def test_returns_409_when_reconciler_not_configured(self, skill_manager):
        ext_module.ai_service_manager.get_skill_reconciler.return_value = None
        handler = _make_handler(SkillsReconcileHandler)
        asyncio.run(SkillsReconcileHandler.post(handler))
        handler.set_status.assert_called_with(409)
        body = _parse_response(handler)
        assert "manifest" in body["error"].lower()

    def test_returns_reconcile_result(self, skill_manager):
        reconciler = MagicMock()
        reconciler.reconcile.return_value = ReconcileResult(
            added=2, updated=1, removed=0, unchanged=3, errors=["boom"]
        )
        ext_module.ai_service_manager.get_skill_reconciler.return_value = reconciler
        handler = _make_handler(SkillsReconcileHandler)
        asyncio.run(SkillsReconcileHandler.post(handler))
        body = _parse_response(handler)
        assert body == {
            "added": 2,
            "updated": 1,
            "removed": 0,
            "unchanged": 3,
            "errors": ["boom"],
        }


class TestSkillsReconcilerStopHandler:
    """Incident-response kill switch endpoint. Stops the background
    reconciler at runtime without a server restart. Not gated by the
    skills_management policy (the intended use is to stop the loop
    regardless of current policy state)."""

    def test_returns_was_running_false_when_reconciler_absent(self, skill_manager):
        ext_module.ai_service_manager.get_skill_reconciler.return_value = None
        handler = _make_handler(SkillsReconcilerStopHandler)
        asyncio.run(SkillsReconcilerStopHandler.post(handler))
        body = _parse_response(handler)
        assert body == {"stopped": True, "was_running": False}
        handler.set_status.assert_not_called()

    def test_stops_running_reconciler(self, skill_manager):
        reconciler = MagicMock()
        reconciler.is_running.return_value = True
        ext_module.ai_service_manager.get_skill_reconciler.return_value = reconciler
        handler = _make_handler(SkillsReconcilerStopHandler)
        asyncio.run(SkillsReconcilerStopHandler.post(handler))
        reconciler.stop.assert_called_once()
        body = _parse_response(handler)
        assert body == {"stopped": True, "was_running": True}

    def test_idempotent_when_already_stopped(self, skill_manager):
        # Second POST after a stop should report was_running=False without
        # erroring, so admins can blindly retry the kill switch from a
        # script.
        reconciler = MagicMock()
        reconciler.is_running.return_value = False
        ext_module.ai_service_manager.get_skill_reconciler.return_value = reconciler
        handler = _make_handler(SkillsReconcilerStopHandler)
        asyncio.run(SkillsReconcilerStopHandler.post(handler))
        reconciler.stop.assert_called_once()
        body = _parse_response(handler)
        assert body == {"stopped": True, "was_running": False}

    def test_not_subject_to_skills_management_policy_gate(self, skill_manager):
        # Pin the deliberate inversion: when an admin force-offs the Skills
        # policy, the rest of /skills/* returns 403, but the stop endpoint
        # must still work — otherwise the kill switch is unreachable in
        # the exact state it exists to support. Verified by inspecting the
        # MRO; a future refactor that adds SkillsBaseHandler to the bases
        # would re-introduce the deadlock.
        assert SkillsBaseHandler not in SkillsReconcilerStopHandler.__mro__


# Per-family policy-gate coverage lives in `tests/test_policy_gate.py`,
# parametrized across SkillsBaseHandler / ClaudeMCPBaseHandler /
# PluginsBaseHandler.


class TestSkillsForceOffSuppressesReconciler:
    """When ``skills_management_policy = force-off``, NBI must not
    construct a ``SkillReconciler`` — even if a manifest is configured.
    Pins the contract documented in the policy's docstring."""

    @pytest.mark.parametrize(
        "policy,expect_empty_manifest",
        [
            ("user-choice", False),
            ("force-on", False),
            ("force-off", True),
        ],
    )
    def test_force_off_empties_manifest_source(self, policy, expect_empty_manifest):
        from notebook_intelligence.feature_flags import is_force_off

        # The relevant logic in `initialize_ai_service` is:
        #     if is_force_off(feature_policies, "skills_management"):
        #         manifest_source = ""
        # Asserting the predicate directly + the post-condition is lighter
        # than spinning up a real NotebookIntelligence instance.
        feature_policies = {"skills_management": policy}
        manifest_source = "https://example.com/m.yaml"
        if is_force_off(feature_policies, "skills_management"):
            manifest_source = ""
        assert (manifest_source == "") is expect_empty_manifest
