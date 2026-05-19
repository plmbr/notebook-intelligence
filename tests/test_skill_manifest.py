import io
from unittest.mock import patch

import pytest

from notebook_intelligence.skill_manifest import (
    ManifestError,
    MAX_MANIFEST_BYTES,
    load_manifest,
    load_manifests,
    split_sources,
)


class TestFileLoading:
    def test_loads_yaml_from_file(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text(
            "skills:\n"
            "  - url: https://github.com/org/repo/tree/main/a\n"
            "  - url: https://github.com/org/repo/tree/main/b\n"
            "    name: beta\n"
            "    scope: project\n",
            encoding="utf-8",
        )
        manifest = load_manifest(str(p))
        assert len(manifest.entries) == 2
        assert manifest.entries[0].url == "https://github.com/org/repo/tree/main/a"
        assert manifest.entries[0].name is None
        assert manifest.entries[0].scope == "user"
        assert manifest.entries[1].name == "beta"
        assert manifest.entries[1].scope == "project"

    def test_loads_json_from_file(self, tmp_path):
        # yaml.safe_load handles JSON as a subset of YAML.
        p = tmp_path / "m.json"
        p.write_text(
            '{"skills": [{"url": "https://github.com/org/repo/tree/main/a"}]}',
            encoding="utf-8",
        )
        manifest = load_manifest(str(p))
        assert len(manifest.entries) == 1

    def test_expands_tilde_in_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        p = tmp_path / "m.yaml"
        p.write_text("skills: []\n", encoding="utf-8")
        manifest = load_manifest("~/m.yaml")
        assert manifest.entries == []

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ManifestError, match="not found"):
            load_manifest(str(tmp_path / "nope.yaml"))

    def test_size_cap_enforced(self, tmp_path):
        p = tmp_path / "big.yaml"
        p.write_bytes(b"a" * (MAX_MANIFEST_BYTES + 10))
        with pytest.raises(ManifestError, match="exceeds"):
            load_manifest(str(p))


class TestValidation:
    def test_rejects_empty_source(self):
        with pytest.raises(ManifestError, match="empty"):
            load_manifest("")

    def test_rejects_non_mapping_root(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text("- url: foo\n", encoding="utf-8")
        with pytest.raises(ManifestError, match="mapping"):
            load_manifest(str(p))

    def test_rejects_missing_skills_key(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text("other: []\n", encoding="utf-8")
        with pytest.raises(ManifestError, match="skills"):
            load_manifest(str(p))

    def test_rejects_non_list_skills(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text("skills:\n  foo: bar\n", encoding="utf-8")
        with pytest.raises(ManifestError, match="must be a list"):
            load_manifest(str(p))

    def test_rejects_entry_missing_url(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text("skills:\n  - name: nope\n", encoding="utf-8")
        with pytest.raises(ManifestError, match="url is required"):
            load_manifest(str(p))

    def test_rejects_invalid_scope(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text(
            "skills:\n  - url: https://x/y\n    scope: global\n", encoding="utf-8"
        )
        with pytest.raises(ManifestError, match="scope"):
            load_manifest(str(p))

    def test_rejects_invalid_name(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text(
            "skills:\n  - url: https://x/y\n    name: Bad Name\n", encoding="utf-8"
        )
        with pytest.raises(ManifestError, match="not a valid skill name"):
            load_manifest(str(p))

    def test_rejects_malformed_yaml(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text("skills: [\n", encoding="utf-8")
        with pytest.raises(ManifestError, match="not valid YAML"):
            load_manifest(str(p))


class TestUrlLoading:
    @staticmethod
    def _fake_response(body: bytes):
        resp = io.BytesIO(body)
        resp.__enter__ = lambda self: self  # type: ignore[attr-defined]
        resp.__exit__ = lambda self, *a: False  # type: ignore[attr-defined]
        return resp

    def test_fetches_over_https(self):
        body = b"skills:\n  - url: https://github.com/org/repo/tree/main/a\n"
        with patch(
            "notebook_intelligence.skill_manifest._urlopen_no_redirect"
        ) as mock_open:
            mock_open.return_value = self._fake_response(body)
            manifest = load_manifest("https://example.com/manifest.yaml")
        assert len(manifest.entries) == 1
        # Verify auth header not set when no token.
        req = mock_open.call_args[0][0]
        assert "Authorization" not in req.headers

    def test_adds_bearer_token_header(self):
        body = b"skills: []\n"
        with patch(
            "notebook_intelligence.skill_manifest._urlopen_no_redirect"
        ) as mock_open:
            mock_open.return_value = self._fake_response(body)
            load_manifest("https://example.com/manifest.yaml", token="abc123")
        req = mock_open.call_args[0][0]
        assert req.headers.get("Authorization") == "Bearer abc123"

    def test_url_size_cap_enforced(self):
        big = b"a" * (MAX_MANIFEST_BYTES + 10)
        with patch(
            "notebook_intelligence.skill_manifest._urlopen_no_redirect"
        ) as mock_open:
            mock_open.return_value = self._fake_response(big)
            with pytest.raises(ManifestError, match="exceeds"):
                load_manifest("https://example.com/manifest.yaml")

    def test_github_host_uses_gh_token_fallback(self):
        body = b"skills: []\n"
        with patch(
            "notebook_intelligence.skill_manifest.resolve_github_token",
            return_value="gh_fallback",
        ), patch(
            "notebook_intelligence.skill_manifest._urlopen_no_redirect"
        ) as mock_open:
            mock_open.return_value = self._fake_response(body)
            load_manifest(
                "https://raw.githubusercontent.com/org/repo/main/manifest.yaml"
            )
        req = mock_open.call_args[0][0]
        assert req.headers.get("Authorization") == "Bearer gh_fallback"

    def test_non_github_host_skips_gh_token_fallback(self):
        body = b"skills: []\n"
        with patch(
            "notebook_intelligence.skill_manifest.resolve_github_token",
            return_value="gh_fallback",
        ) as probe, patch(
            "notebook_intelligence.skill_manifest._urlopen_no_redirect"
        ) as mock_open:
            mock_open.return_value = self._fake_response(body)
            load_manifest("https://example.com/manifest.yaml")
        req = mock_open.call_args[0][0]
        assert "Authorization" not in req.headers
        probe.assert_not_called()

    def test_explicit_token_wins_over_gh_token_fallback(self):
        body = b"skills: []\n"
        with patch(
            "notebook_intelligence.skill_manifest.resolve_github_token",
            return_value="gh_fallback",
        ) as probe, patch(
            "notebook_intelligence.skill_manifest._urlopen_no_redirect"
        ) as mock_open:
            mock_open.return_value = self._fake_response(body)
            load_manifest(
                "https://raw.githubusercontent.com/org/repo/main/manifest.yaml",
                token="explicit",
            )
        req = mock_open.call_args[0][0]
        assert req.headers.get("Authorization") == "Bearer explicit"
        probe.assert_not_called()


class TestSplitSources:
    def test_empty_input_yields_empty_list(self):
        assert split_sources("") == []
        assert split_sources("   ") == []

    def test_single_source(self):
        assert split_sources("https://a/m.yaml") == ["https://a/m.yaml"]

    def test_commas_with_whitespace(self):
        assert split_sources("a, b , c") == ["a", "b", "c"]

    def test_empty_entries_dropped(self):
        # All-comma input degenerates to empty list (feature disabled).
        assert split_sources(",,,") == []
        # Mixed empties stripped from the middle.
        assert split_sources("a,,b,") == ["a", "b"]

    def test_non_string_input_returns_empty(self):
        # Defensive: traitlets pass through whatever the user wrote; an empty
        # list shouldn't crash the wiring.
        assert split_sources(None) == []  # type: ignore[arg-type]


class TestLoadManifests:
    def _write_manifest(self, tmp_path, name, body):
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        return str(p)

    def test_empty_sources_returns_empty(self):
        result = load_manifests([])
        assert result.manifest.entries == []
        assert result.errors == []
        assert result.warnings == []
        assert result.loaded_sources == []

    def test_single_source_passthrough(self, tmp_path):
        source = self._write_manifest(
            tmp_path,
            "m.yaml",
            "skills:\n  - url: https://github.com/org/repo/tree/main/a\n",
        )
        result = load_manifests([source])
        assert len(result.manifest.entries) == 1
        assert result.manifest.entries[0].source == source
        assert result.loaded_sources == [source]
        assert result.errors == []
        assert result.warnings == []

    def test_two_sources_union(self, tmp_path):
        a = self._write_manifest(
            tmp_path,
            "a.yaml",
            "skills:\n  - url: https://github.com/org/repo/tree/main/alpha\n",
        )
        b = self._write_manifest(
            tmp_path,
            "b.yaml",
            "skills:\n  - url: https://github.com/org/repo/tree/main/beta\n",
        )
        result = load_manifests([a, b])
        urls = [e.url for e in result.manifest.entries]
        assert urls == [
            "https://github.com/org/repo/tree/main/alpha",
            "https://github.com/org/repo/tree/main/beta",
        ]
        assert result.errors == []
        assert result.warnings == []
        assert result.loaded_sources == [a, b]

    def test_url_dupe_first_wins_with_warning(self, tmp_path):
        a = self._write_manifest(
            tmp_path,
            "a.yaml",
            "skills:\n  - url: https://github.com/org/repo/tree/main/data-eda\n",
        )
        b = self._write_manifest(
            tmp_path,
            "b.yaml",
            "skills:\n  - url: https://github.com/org/repo/tree/main/data-eda\n"
            "    scope: project\n",
        )
        result = load_manifests([a, b])
        # Only the first occurrence survives.
        assert len(result.manifest.entries) == 1
        assert result.manifest.entries[0].source == a
        assert result.manifest.entries[0].scope == "user"
        # Warning surfaces both sources by name.
        assert len(result.warnings) == 1
        assert "data-eda" in result.warnings[0]
        assert a in result.warnings[0]
        assert b in result.warnings[0]
        assert result.errors == []

    def test_name_collision_skips_second_with_error(self, tmp_path):
        # Two different URLs that resolve to the same explicit name.
        a = self._write_manifest(
            tmp_path,
            "a.yaml",
            "skills:\n  - url: https://github.com/org-a/repo/tree/main/foo\n"
            "    name: shared\n",
        )
        b = self._write_manifest(
            tmp_path,
            "b.yaml",
            "skills:\n  - url: https://github.com/org-b/repo/tree/main/bar\n"
            "    name: shared\n",
        )
        result = load_manifests([a, b])
        assert len(result.manifest.entries) == 1
        assert result.manifest.entries[0].source == a
        assert len(result.errors) == 1
        assert "shared" in result.errors[0]
        assert "org-a" in result.errors[0]
        assert "org-b" in result.errors[0]
        assert result.warnings == []

    def test_name_collision_predicted_from_url_subpath(self, tmp_path):
        # Neither entry sets `name:` explicitly; predicted name comes from the
        # URL's last subpath segment.
        a = self._write_manifest(
            tmp_path,
            "a.yaml",
            "skills:\n  - url: https://github.com/org-a/repo/tree/main/skills/data-eda\n",
        )
        b = self._write_manifest(
            tmp_path,
            "b.yaml",
            "skills:\n  - url: https://github.com/org-b/other/tree/main/data-eda\n",
        )
        result = load_manifests([a, b])
        assert len(result.manifest.entries) == 1
        assert len(result.errors) == 1
        assert "data-eda" in result.errors[0]

    def test_one_source_fails_others_succeed(self, tmp_path):
        good = self._write_manifest(
            tmp_path,
            "good.yaml",
            "skills:\n  - url: https://github.com/org/repo/tree/main/alpha\n",
        )
        bad = str(tmp_path / "does-not-exist.yaml")
        result = load_manifests([good, bad])
        # Successful source still contributes.
        assert len(result.manifest.entries) == 1
        assert result.manifest.entries[0].url.endswith("/alpha")
        # Failure surfaces as an error tagged with the failing source.
        assert len(result.errors) == 1
        assert bad in result.errors[0]
        # loaded_sources excludes the failed one — the reconciler uses this
        # to decide stale-removal is unsafe.
        assert result.loaded_sources == [good]

    def test_all_sources_fail(self, tmp_path):
        result = load_manifests(
            [str(tmp_path / "x.yaml"), str(tmp_path / "y.yaml")]
        )
        assert result.manifest.entries == []
        assert len(result.errors) == 2
        assert result.loaded_sources == []

    def test_token_passed_through_to_each_source(self):
        body = b"skills: []\n"
        from io import BytesIO

        def fake_resp(_body):
            resp = BytesIO(_body)
            resp.__enter__ = lambda self: self  # type: ignore[attr-defined]
            resp.__exit__ = lambda self, *a: False  # type: ignore[attr-defined]
            return resp

        with patch(
            "notebook_intelligence.skill_manifest._urlopen_no_redirect"
        ) as mock_open:
            # Fresh response per call; reusing a single BytesIO closes after
            # the first context-manager exit.
            mock_open.side_effect = [fake_resp(body), fake_resp(body)]
            load_manifests(
                [
                    "https://example.com/a.yaml",
                    "https://example.com/b.yaml",
                ],
                token="shared-token",
            )
        # Both calls saw the same Authorization header.
        assert mock_open.call_count == 2
        for call in mock_open.call_args_list:
            req = call.args[0]
            assert req.headers.get("Authorization") == "Bearer shared-token"

    def test_name_collision_via_slugging(self, tmp_path):
        # Predicted-name dedupe must run through the same slug step as the
        # real installer: an entry with a subpath that slugs to "data-eda"
        # collides with another manifest's URL whose subpath segment also
        # slugs to "data-eda" (different casing / repo / owner).
        a = self._write_manifest(
            tmp_path,
            "slug-a.yaml",
            "skills:\n"
            "  - url: https://github.com/org-a/repo/tree/main/skills/data-eda\n",
        )
        # `Data_EDA` in the subpath slugs to `data-eda`. Without _slug(), the
        # raw segment ("Data_EDA") would not match "data-eda" and dedupe
        # would slip through.
        b = self._write_manifest(
            tmp_path,
            "slug-b.yaml",
            "skills:\n"
            "  - url: https://github.com/org-b/other/tree/main/Data_EDA\n",
        )
        result = load_manifests([a, b])
        assert len(result.manifest.entries) == 1
        assert len(result.errors) == 1
        assert "data-eda" in result.errors[0]

    def test_non_github_url_warns_and_keeps_entry(self, tmp_path):
        # A filesystem path or non-GitHub URL used as an entry URL fails
        # parse; predicted-name dedupe drops out with a warning so the
        # operator knows the cross-manifest check didn't run.
        a = self._write_manifest(
            tmp_path,
            "weird.yaml",
            "skills:\n  - url: /opt/local-skill\n",
        )
        result = load_manifests([a])
        # The entry survives (only cross-manifest dedupe was skipped).
        assert len(result.manifest.entries) == 1
        assert len(result.warnings) == 1
        assert "cannot predict installed name" in result.warnings[0]

    def test_partial_failure_missing_first(self, tmp_path):
        # The reverse ordering of the partial-failure test in the reconciler
        # suite: broken source first, good source second. Iteration order
        # shouldn't change which entries survive or which errors fire.
        missing = str(tmp_path / "nope.yaml")
        good = self._write_manifest(
            tmp_path,
            "good.yaml",
            "skills:\n  - url: https://github.com/org/repo/tree/main/alpha\n",
        )
        result = load_manifests([missing, good])
        assert len(result.manifest.entries) == 1
        assert result.manifest.entries[0].url.endswith("/alpha")
        assert len(result.errors) == 1
        assert missing in result.errors[0]
        assert result.loaded_sources == [good]

    def test_url_fetch_error_isolated(self):
        # A urllib URLError on one source must not stop the loader from
        # picking up the next; the failure surfaces in `errors` and the
        # source drops from `loaded_sources`.
        from io import BytesIO
        from urllib.error import URLError

        def fake_resp(body):
            resp = BytesIO(body)
            resp.__enter__ = lambda self: self  # type: ignore[attr-defined]
            resp.__exit__ = lambda self, *a: False  # type: ignore[attr-defined]
            return resp

        good_body = b"skills:\n  - url: https://github.com/org/repo/tree/main/x\n"

        def opener(req, timeout):
            if "broken" in req.full_url:
                raise URLError("connection refused")
            return fake_resp(good_body)

        with patch(
            "notebook_intelligence.skill_manifest._urlopen_no_redirect",
            side_effect=opener,
        ):
            result = load_manifests(
                [
                    "https://example.com/broken.yaml",
                    "https://example.com/good.yaml",
                ]
            )
        assert len(result.manifest.entries) == 1
        assert any("broken" in e for e in result.errors)
        assert result.loaded_sources == ["https://example.com/good.yaml"]

    def test_order_preserved_across_sources(self, tmp_path):
        # Entries appear in the order their source was listed, and in the
        # order they appear inside each source. Stable order matters for the
        # first-wins dedupe contract.
        a = self._write_manifest(
            tmp_path,
            "a.yaml",
            "skills:\n"
            "  - url: https://github.com/org/repo/tree/main/a1\n"
            "  - url: https://github.com/org/repo/tree/main/a2\n",
        )
        b = self._write_manifest(
            tmp_path,
            "b.yaml",
            "skills:\n  - url: https://github.com/org/repo/tree/main/b1\n",
        )
        result = load_manifests([a, b])
        assert [e.url for e in result.manifest.entries] == [
            "https://github.com/org/repo/tree/main/a1",
            "https://github.com/org/repo/tree/main/a2",
            "https://github.com/org/repo/tree/main/b1",
        ]
