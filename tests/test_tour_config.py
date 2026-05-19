# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Unit tests for the admin tour-config loader.

The loader's contract is "fail closed": any unreadable file, schema
violation, or parse error returns {} and logs a warning. These tests
pin both the happy paths and the various failure modes so a future
refactor can't silently start crashing on a malformed admin file.
"""

import json
import logging
import os
import textwrap

import pytest

from notebook_intelligence.tour_config import (
    MAX_COMMAND_LABEL_CHARS,
    MAX_DESCRIPTION_CHARS,
    MAX_TITLE_CHARS,
    MAX_TOUR_CONFIG_BYTES,
    _VALID_STEP_IDS,
    load_tour_config,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
TOUR_DEFAULTS_PATH = os.path.join(REPO_ROOT, "src", "tour", "tour-defaults.json")


def _write(path, body):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


class TestEmptyAndMissing:
    def test_returns_empty_when_path_is_none(self):
        assert load_tour_config(None) == {}

    def test_returns_empty_when_path_is_blank(self):
        assert load_tour_config("") == {}

    def test_returns_empty_when_file_missing(self, tmp_path):
        # Silent: the steady state for almost every deployment is no
        # admin file, and we don't want to spam logs.
        assert load_tour_config(str(tmp_path / "does-not-exist.yaml")) == {}

    def test_returns_empty_for_empty_file(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        assert load_tour_config(str(path)) == {}


class TestParsing:
    def test_loads_yaml_overrides(self, tmp_path):
        path = tmp_path / "tour.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  welcome:
                    title: "Hello team"
                    description: "Two sentences. Press Esc to skip."
                  drag-and-drop:
                    enabled: false
                  launcher-tiles:
                    description_singular: "{launchers} opens a terminal."
                    description_plural: "Each of {launchers} opens a terminal."
                ui:
                  skip: "Dismiss"
                """
            ),
        )
        result = load_tour_config(str(path))
        assert result["steps"]["welcome"]["title"] == "Hello team"
        assert (
            result["steps"]["welcome"]["description"]
            == "Two sentences. Press Esc to skip."
        )
        assert result["steps"]["drag-and-drop"]["enabled"] is False
        assert (
            result["steps"]["launcher-tiles"]["description_singular"]
            == "{launchers} opens a terminal."
        )
        assert result["ui"]["skip"] == "Dismiss"

    def test_loads_json_overrides(self, tmp_path):
        # JSON is a subset of YAML so yaml.safe_load handles it; the
        # admin can ship either format.
        path = tmp_path / "tour.json"
        path.write_text(
            json.dumps(
                {
                    "steps": {
                        "welcome": {"title": "Hi"},
                    }
                }
            )
        )
        assert load_tour_config(str(path)) == {
            "steps": {"welcome": {"title": "Hi"}}
        }

    def test_malformed_yaml_returns_empty_with_warning(self, tmp_path, caplog):
        path = tmp_path / "bad.yaml"
        # Unclosed flow mapping; yaml raises.
        path.write_text("steps: { welcome: { title: 'unterminated\n")
        with caplog.at_level(logging.WARNING):
            assert load_tour_config(str(path)) == {}
        assert any("parse failed" in r.message for r in caplog.records)

    def test_oversize_file_returns_empty_with_warning(self, tmp_path, caplog):
        path = tmp_path / "huge.yaml"
        path.write_text("steps:\n  welcome:\n    title: " +
                        ("x" * (MAX_TOUR_CONFIG_BYTES + 64)))
        with caplog.at_level(logging.WARNING):
            assert load_tour_config(str(path)) == {}
        assert any("exceeds" in r.message and "cap" in r.message
                   for r in caplog.records)

    def test_non_mapping_root_returns_empty(self, tmp_path, caplog):
        path = tmp_path / "list.yaml"
        path.write_text("- welcome\n- done\n")
        with caplog.at_level(logging.WARNING):
            assert load_tour_config(str(path)) == {}
        assert any(
            "top-level value must be a mapping" in r.message for r in caplog.records
        )


class TestSchemaValidation:
    def test_unknown_top_level_key_warns_and_drops(self, tmp_path, caplog):
        path = tmp_path / "extra.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  welcome:
                    title: "Hi"
                extra_top_level: oops
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        # Steps section still applied; extra dropped.
        assert result == {"steps": {"welcome": {"title": "Hi"}}}
        assert any(
            "extra_top_level is not a recognized" in r.message
            for r in caplog.records
        )

    def test_unknown_step_id_warns_and_drops(self, tmp_path, caplog):
        path = tmp_path / "typo.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  welcom:  # typo
                    title: "Hi"
                  welcome:
                    title: "Hi for real"
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        assert result == {"steps": {"welcome": {"title": "Hi for real"}}}
        assert any(
            "steps.welcom is not a known step id" in r.message
            for r in caplog.records
        )

    def test_unknown_step_field_warns_and_drops(self, tmp_path, caplog):
        path = tmp_path / "extra.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  welcome:
                    title: "Hi"
                    placement: top  # not allowed
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        assert result == {"steps": {"welcome": {"title": "Hi"}}}
        assert any("placement is not a recognized" in r.message
                   for r in caplog.records)

    def test_launcher_tile_templates_allowed_on_launcher_step(self, tmp_path):
        path = tmp_path / "lt.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  launcher-tiles:
                    description_singular: "One: {launchers}"
                    description_plural: "Many: {launchers}"
                """
            ),
        )
        result = load_tour_config(str(path))
        assert (
            result["steps"]["launcher-tiles"]["description_singular"]
            == "One: {launchers}"
        )

    def test_launcher_tile_templates_rejected_on_other_steps(
        self, tmp_path, caplog
    ):
        path = tmp_path / "wrong.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  welcome:
                    description_singular: "doesn't apply here"
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        # The unknown field gets stripped; the step ends up with no
        # overrides at all, so it's dropped from the cleaned dict.
        assert result == {}

    def test_enabled_as_string_is_rejected(self, tmp_path, caplog):
        path = tmp_path / "boolish.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  drag-and-drop:
                    enabled: "true"
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        assert result == {}
        assert any("enabled must be true/false" in r.message
                   for r in caplog.records)

    def test_non_string_title_rejected(self, tmp_path, caplog):
        path = tmp_path / "weird.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  welcome:
                    title: 42
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        assert result == {}

    def test_unknown_ui_key_warns_and_drops(self, tmp_path, caplog):
        path = tmp_path / "ui.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                ui:
                  skip: "Cancel"
                  whatever: "ignored"
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        assert result == {"ui": {"skip": "Cancel"}}
        assert any("ui.whatever is not a recognized" in r.message
                   for r in caplog.records)


class TestLengthCaps:
    def test_long_title_is_truncated(self, tmp_path, caplog):
        long_title = "x" * (MAX_TITLE_CHARS + 50)
        path = tmp_path / "long.yaml"
        _write(
            path,
            textwrap.dedent(
                f"""
                steps:
                  welcome:
                    title: "{long_title}"
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        assert len(result["steps"]["welcome"]["title"]) == MAX_TITLE_CHARS
        assert any("title truncated" in r.message for r in caplog.records)

    def test_long_description_is_truncated(self, tmp_path):
        long_desc = "y" * (MAX_DESCRIPTION_CHARS + 50)
        path = tmp_path / "long.yaml"
        _write(
            path,
            textwrap.dedent(
                f"""
                steps:
                  welcome:
                    description: "{long_desc}"
                """
            ),
        )
        result = load_tour_config(str(path))
        assert (
            len(result["steps"]["welcome"]["description"])
            == MAX_DESCRIPTION_CHARS
        )


class TestIntegrationShape:
    def test_returns_only_sections_with_content(self, tmp_path):
        # If every override turned out to be invalid, the section is
        # omitted entirely so the frontend doesn't see an empty `steps`
        # dict and have to special-case it.
        path = tmp_path / "junk.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  welcome:
                    unknown: "x"
                """
            ),
        )
        assert load_tour_config(str(path)) == {}

    def test_partial_apply_keeps_valid_fields(self, tmp_path):
        # Mixing valid and invalid fields: valid stays, invalid drops.
        path = tmp_path / "mixed.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  welcome:
                    title: "Good"
                    placement: top  # unknown -> drop
                  done:
                    enabled: "not a bool"  # type error -> drop
                """
            ),
        )
        result = load_tour_config(str(path))
        assert result == {"steps": {"welcome": {"title": "Good"}}}


class TestSecurity:
    def test_python_object_construction_tag_rejected(self, tmp_path, caplog):
        # safe_load already refuses construction tags; pinning this so a
        # future swap to yaml.load can't silently re-enable code exec.
        path = tmp_path / "evil.yaml"
        path.write_text("steps: !!python/object/apply:os.system ['echo pwned']\n")
        with caplog.at_level(logging.WARNING):
            assert load_tour_config(str(path)) == {}
        assert any("parse failed" in r.message for r in caplog.records)


class TestEmptyStrings:
    def test_empty_title_is_rejected(self, tmp_path, caplog):
        path = tmp_path / "empty-title.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  welcome:
                    title: ""
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        assert result == {}
        assert any("title is empty" in r.message for r in caplog.records)

    def test_empty_ui_label_is_rejected(self, tmp_path, caplog):
        path = tmp_path / "empty-ui.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                ui:
                  skip: ""
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        assert result == {}
        assert any("ui.skip is empty" in r.message for r in caplog.records)


class TestLauncherTilesGuard:
    def test_plain_description_rejected_on_launcher_tiles(self, tmp_path, caplog):
        # The launcher-tiles description is a runtime thunk on the
        # frontend; admins must use description_singular / _plural.
        # Reject the plain `description` field outright so a typo
        # doesn't silently no-op.
        path = tmp_path / "lt-bad.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  launcher-tiles:
                    description: "this is dropped on the frontend"
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        assert result == {}
        assert any(
            "steps.launcher-tiles.description is not a recognized" in r.message
            for r in caplog.records
        )


class TestWarningDedup:
    def test_repeated_issues_collapse_to_one_log_line(self, tmp_path, caplog):
        # The validator accumulates warnings and dedups before emit so a
        # file with N copies of the same typo doesn't produce N log
        # lines per capabilities call.
        path = tmp_path / "dup.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                steps:
                  welcome:
                    bogus_field: 1
                  done:
                    bogus_field: 2
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            load_tour_config(str(path))
        # Two distinct messages (one per step), but each emitted once.
        emitted = [r.message for r in caplog.records if "is not a recognized" in r.message or "issue(s) ignored" in r.message]
        flush_lines = [m for m in emitted if "issue(s) ignored" in m]
        assert len(flush_lines) == 1
        assert "welcome.bogus_field" in flush_lines[0]
        assert "done.bogus_field" in flush_lines[0]


class TestCommandSection:
    def test_command_label_override_accepted(self, tmp_path):
        path = tmp_path / "cmd.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                command:
                  label: "Replay ACME walkthrough"
                """
            ),
        )
        assert load_tour_config(str(path)) == {
            "command": {"label": "Replay ACME walkthrough"}
        }

    def test_unknown_command_field_dropped(self, tmp_path, caplog):
        path = tmp_path / "cmd.yaml"
        _write(
            path,
            textwrap.dedent(
                """
                command:
                  label: "OK"
                  bogus: "ignored"
                """
            ),
        )
        with caplog.at_level(logging.WARNING):
            result = load_tour_config(str(path))
        assert result == {"command": {"label": "OK"}}
        assert any(
            "command.bogus is not a recognized" in r.message
            for r in caplog.records
        )

    def test_long_command_label_truncated(self, tmp_path):
        path = tmp_path / "cmd.yaml"
        long_label = "z" * (MAX_COMMAND_LABEL_CHARS + 20)
        _write(
            path,
            textwrap.dedent(
                f"""
                command:
                  label: "{long_label}"
                """
            ),
        )
        result = load_tour_config(str(path))
        assert len(result["command"]["label"]) == MAX_COMMAND_LABEL_CHARS


class TestDefaultsBundle:
    """Pin the bundled defaults file against the validator schema.

    The default copy ships as a JSON whose shape is identical to an
    admin override file. These tests catch drift between the bundled
    defaults, the validator's known-step set, and the cap policies.
    Without them, an edit to one side can silently invalidate the
    other.
    """

    def test_defaults_file_passes_validator_cleanly(self, caplog):
        # Loading the bundled defaults through the same validator an
        # admin file gets should produce no warnings; the bundled copy
        # is the authoritative example of a well-formed override.
        with caplog.at_level(logging.WARNING):
            cleaned = load_tour_config(TOUR_DEFAULTS_PATH)
        assert cleaned, "defaults should produce a non-empty cleaned dict"
        # Steps section round-trips identically (no truncation, no
        # rejected fields).
        with open(TOUR_DEFAULTS_PATH, "r", encoding="utf-8") as fh:
            raw = json.loads(fh.read())
        assert set(cleaned["steps"].keys()) == set(raw["steps"].keys())
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
            "defaults file produced WARN: "
            + "; ".join(r.message for r in caplog.records)
        )

    def test_defaults_file_step_ids_match_validator_allowlist(self):
        # Schema drift between _VALID_STEP_IDS (Python) and the JSON
        # keys would let an admin's override-of-a-renamed-step silently
        # disappear with no warning. Pin them equal here.
        with open(TOUR_DEFAULTS_PATH, "r", encoding="utf-8") as fh:
            raw = json.loads(fh.read())
        assert set(raw["steps"].keys()) == _VALID_STEP_IDS


class TestIOErrorBranches:
    def test_getsize_oserror_returns_empty_with_warning(
        self, tmp_path, caplog, monkeypatch
    ):
        path = tmp_path / "exists.yaml"
        path.write_text("steps: {}")

        def boom(_p):
            raise OSError("stat busted")

        monkeypatch.setattr("notebook_intelligence.tour_config.os.path.getsize", boom)
        with caplog.at_level(logging.WARNING):
            assert load_tour_config(str(path)) == {}
        assert any("stat failed" in r.message for r in caplog.records)

    def test_open_oserror_returns_empty_with_warning(
        self, tmp_path, caplog, monkeypatch
    ):
        path = tmp_path / "exists.yaml"
        path.write_text("steps: {}")

        real_open = open

        def boom(p, *args, **kwargs):
            if str(p) == str(path):
                raise OSError("EACCES")
            return real_open(p, *args, **kwargs)

        monkeypatch.setattr("builtins.open", boom)
        with caplog.at_level(logging.WARNING):
            assert load_tour_config(str(path)) == {}
        assert any("read failed" in r.message for r in caplog.records)
