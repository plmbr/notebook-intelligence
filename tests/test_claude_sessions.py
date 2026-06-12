import json
import os
from pathlib import Path

import pytest

from notebook_intelligence.claude_sessions import (
    ClaudeSessionInfo,
    _CONTROL_SLASH_COMMANDS,
    encode_cwd,
    get_sessions_dir,
    _list_sessions_in_dir,
    list_all_sessions,
)


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for obj in lines:
            fh.write(json.dumps(obj) + "\n")


def _user_line(session_id: str, text: str, cwd: str = "") -> dict:
    line = {
        "type": "user",
        "message": {"role": "user", "content": text},
        "sessionId": session_id,
    }
    if cwd:
        line["cwd"] = cwd
    return line


def _sidechain_line(session_id: str, content: str = "Warmup") -> dict:
    return {
        "type": "user",
        "isSidechain": True,
        "message": {"role": "user", "content": content},
        "sessionId": session_id,
    }


def _assistant_line(session_id: str, cwd: str = "") -> dict:
    line = {
        "type": "assistant",
        "message": {"role": "assistant", "content": "ok"},
        "sessionId": session_id,
    }
    if cwd:
        line["cwd"] = cwd
    return line


@pytest.fixture(autouse=True)
def _clear_session_cache():
    """Drop the module-level _SESSION_INFO_CACHE between tests.

    The cache is keyed by (path, mtime), so under tmp_path per-test
    isolation collisions are theoretical; explicit clearing keeps test
    ordering, single-test reruns, and future cache-introspection tests
    deterministic instead of relying on tmp_path entropy.
    """
    from notebook_intelligence import claude_sessions

    claude_sessions._SESSION_INFO_CACHE.clear()
    yield
    claude_sessions._SESSION_INFO_CACHE.clear()


@pytest.fixture
def fake_claude_home(tmp_path):
    """Create an empty ~/.claude stand-in under a tmp_path."""
    home = tmp_path / "claude_home"
    home.mkdir()
    return home


@pytest.fixture
def project_cwd(tmp_path):
    """Create an arbitrary project directory to act as the Jupyter cwd."""
    cwd = tmp_path / "projects" / "my-notebook"
    cwd.mkdir(parents=True)
    return str(cwd)


@pytest.fixture
def sessions_dir(fake_claude_home, project_cwd):
    return get_sessions_dir(project_cwd, claude_home=str(fake_claude_home))


class TestEncodeCwd:
    def test_replaces_path_separators_with_dashes(self):
        assert encode_cwd("/Users/me/proj") == "-Users-me-proj"

    def test_normalizes_trailing_slash(self):
        assert encode_cwd("/Users/me/proj/") == "-Users-me-proj"

    def test_normalizes_parent_segments(self):
        assert encode_cwd("/Users/me/proj/../proj") == "-Users-me-proj"

    def test_resolves_symlinks(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)

        assert encode_cwd(str(link)) == encode_cwd(str(real))


class TestGetSessionsDir:
    def test_composes_claude_projects_path(self, fake_claude_home, project_cwd):
        result = get_sessions_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result == fake_claude_home / "projects" / encode_cwd(project_cwd)


class TestListSessions:
    def test_returns_empty_when_dir_missing(
        self, fake_claude_home, project_cwd
    ):
        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result == []

    def test_returns_empty_when_dir_has_no_jsonl_files(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "notes.txt").write_text("hi")
        (sessions_dir / "subagents").mkdir()

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result == []

    def test_lists_sessions_with_metadata(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        session_id = "abc123"
        path = sessions_dir / f"{session_id}.jsonl"
        _write_jsonl(
            path,
            [
                _user_line(session_id, "Help me fix this bug"),
                _assistant_line(session_id),
                _user_line(session_id, "Follow-up question"),
            ],
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))

        assert len(result) == 1
        session = result[0]
        assert isinstance(session, ClaudeSessionInfo)
        assert session.session_id == session_id
        assert session.preview == "Help me fix this bug"
        assert session.path == str(path)

    def test_sorts_sessions_newest_first(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        older_path = sessions_dir / "older.jsonl"
        newer_path = sessions_dir / "newer.jsonl"
        _write_jsonl(older_path, [_user_line("older", "first")])
        _write_jsonl(newer_path, [_user_line("newer", "second")])

        # Force distinct mtimes regardless of filesystem resolution.
        os.utime(older_path, (1_000_000_000, 1_000_000_000))
        os.utime(newer_path, (2_000_000_000, 2_000_000_000))

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))

        assert [s.session_id for s in result] == ["newer", "older"]

    def test_skips_files_without_user_messages(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # A transcript that only contains a file-history-snapshot should be
        # filtered out so the picker doesn't show an empty row.
        snapshot_only = sessions_dir / "snapshot.jsonl"
        _write_jsonl(
            snapshot_only,
            [{"type": "file-history-snapshot", "messageId": "x", "snapshot": {}}],
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result == []

    def test_ignores_nested_subagent_files(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Subagent transcripts live under a nested subagents/ directory and
        # must not surface as top-level sessions.
        main_path = sessions_dir / "main.jsonl"
        _write_jsonl(main_path, [_user_line("main", "hello")])

        nested = sessions_dir / "main" / "subagents"
        nested.mkdir(parents=True)
        _write_jsonl(
            nested / "agent-xyz.jsonl", [_user_line("sub", "sub prompt")]
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert [s.session_id for s in result] == ["main"]

    def test_skips_top_level_sidechain_files(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Some Claude Agent SDK setups land sidechain "Warmup" probes (the
        # /clear pre-roll) at the top level under short agent-* names.
        # These aren't resumable via `claude --resume`, so they must not show
        # up in the picker.
        _write_jsonl(
            sessions_dir / "real-session.jsonl",
            [_user_line("real-session", "hello")],
        )
        _write_jsonl(
            sessions_dir / "agent-a94b68b.jsonl",
            [_sidechain_line("real-session")],
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert [s.session_id for s in result] == ["real-session"]

    def test_sidechain_filter_skips_corrupt_first_line(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # A malformed first line falls through to the next; if that next line
        # is a sidechain, the file is still filtered.
        sessions_dir.mkdir(parents=True)
        path = sessions_dir / "agent-corrupt.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write("{ broken\n")
            fh.write(json.dumps(_sidechain_line("real-session")) + "\n")

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result == []

    def test_keeps_files_when_isSidechain_is_false(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Real sessions explicitly mark isSidechain:false; treat them as
        # normal even though the field is present.
        line = {
            "type": "user",
            "isSidechain": False,
            "message": {"role": "user", "content": "hello"},
            "sessionId": "real",
        }
        _write_jsonl(sessions_dir / "real.jsonl", [line])

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert [s.session_id for s in result] == ["real"]

    def test_skips_nbi_context_preamble_when_extracting_preview(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # NBI prepends an "Additional context: ..." user message before the
        # real prompt; the preview should reflect the user's intent, not the
        # boilerplate.
        preamble = _user_line(
            "real",
            "Additional context: Current directory open in Jupyter is: "
            "'/tmp/proj' and current file is: 'foo.ipynb'",
        )
        real_prompt = _user_line("real", "Implement fizzbuzz in a new cell")
        _write_jsonl(sessions_dir / "real.jsonl", [preamble, real_prompt])

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].preview == "Implement fizzbuzz in a new cell"

    def test_skips_preamble_in_structured_content(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Same shape, but the preamble arrives as a list of content blocks.
        preamble = _user_line(
            "real",
            [
                {
                    "type": "text",
                    "text": (
                        "Additional context: Current directory open in "
                        "Jupyter is: ''"
                    ),
                }
            ],
        )
        real_prompt = _user_line("real", "Hello world")
        _write_jsonl(sessions_dir / "real.jsonl", [preamble, real_prompt])

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert [s.preview for s in result] == ["Hello world"]

    def test_unwraps_joined_preamble_and_prompt_in_one_message(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Repro for issue #329: claude.py joins consecutive user-role
        # messages with "\n" before handing them to the SDK, so a session
        # whose only turn is preamble + prompt gets recorded as one
        # combined user message. The picker must still surface the user's
        # prompt as the preview (and must not drop the session as
        # "all-skippable").
        joined = _user_line(
            "real",
            "Additional context: Current directory open in Jupyter is: ''\n"
            "How can I load JSON from a URL and save as dataframe?",
        )
        _write_jsonl(sessions_dir / "real.jsonl", [joined])

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert (
            result[0].preview
            == "How can I load JSON from a URL and save as dataframe?"
        )

    def test_unwraps_joined_preamble_in_structured_content(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Same joined-on-newline shape, but the content arrives as a
        # single content block (the Anthropic structured form). The
        # block.text is the combined preamble + prompt string.
        joined = _user_line(
            "real",
            [
                {
                    "type": "text",
                    "text": (
                        "Additional context: Current directory open in "
                        "Jupyter is: ''\nHello world"
                    ),
                }
            ],
        )
        _write_jsonl(sessions_dir / "real.jsonl", [joined])

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert [s.preview for s in result] == ["Hello world"]

    def test_joined_preamble_with_skippable_prompt_still_skips(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # When the preamble is joined with another skippable form (a
        # control slash command, here), the combined message must
        # still be treated as skippable so the picker keeps scanning
        # for a real prompt instead of using "/exit" as the preview.
        # Exercises the recursive call's path through the legacy
        # _CONTROL_SLASH_COMMANDS check.
        joined = _user_line(
            "real",
            "Additional context: Current directory open in Jupyter is: ''\n/exit",
        )
        real_prompt = _user_line("real", "Plot a sine wave")
        _write_jsonl(sessions_dir / "real.jsonl", [joined, real_prompt])

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert [s.preview for s in result] == ["Plot a sine wave"]

    def test_joined_preamble_alone_without_newline_still_skips(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Pins the `newline_at == -1` branch of the helper: when the
        # transcript records the preamble with no trailing newline /
        # prompt (a single-context-update turn), the helper returns
        # an empty string and the recursive _is_skippable_text call
        # bottoms out on the empty-stripped guard.
        preamble_only = _user_line(
            "real",
            "Additional context: Current directory open in Jupyter is: ''",
        )
        _write_jsonl(sessions_dir / "real.jsonl", [preamble_only])

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].preview == ""

    def test_joined_preamble_with_empty_post_newline_still_skips(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # A preamble followed by only whitespace after the newline
        # should behave like the preamble-alone case. The recursive
        # _is_skippable_text call sees whitespace-only text, .strip()s
        # to "", and skips via the empty-stripped guard.
        whitespace_tail = _user_line(
            "real",
            "Additional context: Current directory open in Jupyter is: ''\n   \n",
        )
        _write_jsonl(sessions_dir / "real.jsonl", [whitespace_tail])

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].preview == ""

    def test_keeps_skippable_only_session_with_empty_preview(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Sessions whose user messages are all skippable (e.g. only the
        # NBI preamble, or only "/exit") are still resumable, so they're
        # listed with an empty preview rather than dropped. The picker
        # UI shows just the session id + timestamp (issue #187).
        preamble = _user_line(
            "real", "Additional context: Current directory open in Jupyter is: ''"
        )
        _write_jsonl(sessions_dir / "real.jsonl", [preamble])

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].preview == ""

    def test_skips_claude_code_command_envelopes(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Claude Code itself wraps slash-command artifacts in synthetic user
        # messages: <local-command-caveat>, <command-name>, <local-command-
        # stdout>. None of these are real user prompts.
        envelopes = [
            _user_line(
                "real",
                "<local-command-caveat>Caveat: The messages below were "
                "generated by the user while running local commands."
                "</local-command-caveat>",
            ),
            _user_line("real", "<command-name>/clear</command-name>"),
            _user_line(
                "real", "<local-command-stdout>Bye!</local-command-stdout>"
            ),
        ]
        real_prompt = _user_line("real", "Tell me about pandas")
        _write_jsonl(sessions_dir / "real.jsonl", envelopes + [real_prompt])

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert [s.preview for s in result] == ["Tell me about pandas"]

    def test_tolerates_partial_trailing_line(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Sessions that are still being written can have a half-flushed
        # trailing line; we should keep parsing earlier messages instead of
        # dropping the whole file.
        sessions_dir.mkdir(parents=True)
        path = sessions_dir / "partial.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(_user_line("partial", "first message")) + "\n")
            fh.write('{"type": "user", "message": {"role": "user", "content')

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].preview == "first message"

    def test_preview_is_truncated(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        long_text = "a" * 500
        _write_jsonl(
            sessions_dir / "long.jsonl",
            [_user_line("long", long_text)],
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert len(result[0].preview) < len(long_text)
        assert result[0].preview.endswith("\u2026")

    def test_preview_collapses_whitespace(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        _write_jsonl(
            sessions_dir / "ws.jsonl",
            [_user_line("ws", "line one\n\n   line two\tthree")],
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result[0].preview == "line one line two three"

    def test_handles_structured_content_blocks(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        _write_jsonl(
            sessions_dir / "blocks.jsonl",
            [
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "hello"},
                            {"type": "image", "source": {}},
                            {"type": "text", "text": "world"},
                        ],
                    },
                }
            ],
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result[0].preview == "hello world"

    @pytest.mark.parametrize(
        "first_line, expected_preview",
        [
            # Claude Code injects "[Request interrupted by user...]" markers
            # when the user cancels mid-tool-call.
            ("[Request interrupted by user for tool use]", "real prompt"),
            # claude-agent-sdk echoes "Unknown slash command: <name>" when a
            # CLI-only slash command reaches it (e.g. /clear).
            ("Unknown slash command: clear", "real prompt"),
            # Bare slash verbs (/exit, /clear, /quit, /help) don't describe
            # the session.
            ("/exit", "real prompt"),
            # ...but slash commands WITH args carry real intent — only bare
            # verbs are skipped.
            ("/explain how this works", "/explain how this works"),
            # Empty / whitespace-only first messages aren't useful previews.
            ("   \n\t  ", "real prompt"),
        ],
        ids=[
            "request_interrupted",
            "unknown_slash_echo",
            "bare_slash",
            "slash_with_args",
            "whitespace_only",
        ],
    )
    def test_skip_filter_picks_meaningful_first_message(
        self,
        sessions_dir,
        fake_claude_home,
        project_cwd,
        first_line,
        expected_preview,
    ):
        _write_jsonl(
            sessions_dir / "session.jsonl",
            [
                _user_line("session", first_line),
                _user_line("session", "real prompt"),
            ],
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result[0].preview == expected_preview

    @pytest.mark.parametrize("verb", sorted(_CONTROL_SLASH_COMMANDS))
    def test_every_control_slash_command_is_skipped(
        self, sessions_dir, fake_claude_home, project_cwd, verb
    ):
        # Pin every entry in _CONTROL_SLASH_COMMANDS so a typo or accidental
        # removal in the constant fails this test loudly.
        _write_jsonl(
            sessions_dir / "verb.jsonl",
            [
                _user_line("verb", verb),
                _user_line("verb", "real prompt"),
            ],
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result[0].preview == "real prompt"

    def test_bare_slash_verb_not_in_allowlist_is_kept(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # The allowlist is intentionally narrow — only known control verbs
        # are skipped. A bare unknown slash word (e.g. "/explain", "/voice")
        # is treated as the user's intent and surfaced as the preview.
        _write_jsonl(
            sessions_dir / "unknown.jsonl",
            [_user_line("unknown", "/explain")],
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result[0].preview == "/explain"

    def test_skips_tool_result_user_envelopes(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Tool results are wrapped in user messages but carry no real
        # prompt text. They should not steal the preview from a real user
        # turn.
        _write_jsonl(
            sessions_dir / "tools.jsonl",
            [
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "abc",
                                "content": "done",
                            }
                        ],
                    },
                },
                _user_line("tools", "actual prompt"),
            ],
        )

        result = _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result[0].preview == "actual prompt"


def _history_line(session_id: str, project: str, ts: int, display: str) -> dict:
    return {
        "sessionId": session_id,
        "project": project,
        "timestamp": ts,
        "display": display,
    }


def _write_history(home: Path, lines: list[dict]) -> None:
    _write_jsonl(home / "history.jsonl", lines)


class TestListAllSessions:
    def test_returns_empty_when_no_history(self, fake_claude_home):
        result = list_all_sessions(claude_home=str(fake_claude_home))
        assert result == []

    def test_returns_cwd_sessions_when_history_missing(
        self, fake_claude_home, sessions_dir, project_cwd
    ):
        # The project-walk path finds the session even when history.jsonl
        # is absent (the common case on recent Claude Code releases).
        _write_jsonl(
            sessions_dir / "s1.jsonl",
            [_user_line("s1", "nbi session", cwd=project_cwd)],
        )
        result = list_all_sessions(cwd=project_cwd, claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].session_id == "s1"
        assert result[0].cwd == project_cwd

    def test_merges_cwd_sessions_not_in_history(
        self, fake_claude_home, sessions_dir, project_cwd
    ):
        # history.jsonl has session "hist-only"
        hist_jsonl = sessions_dir / "hist-only.jsonl"
        _write_jsonl(hist_jsonl, [_user_line("hist-only", "from history")])
        _write_history(
            fake_claude_home,
            [_history_line("hist-only", project_cwd, 2_000_000_000_000, "from history")],
        )

        # cwd dir also has "nbi-only" which is not in history.jsonl
        _write_jsonl(
            sessions_dir / "nbi-only.jsonl", [_user_line("nbi-only", "nbi session")]
        )

        result = list_all_sessions(cwd=project_cwd, claude_home=str(fake_claude_home))
        ids = [s.session_id for s in result]
        assert "hist-only" in ids
        assert "nbi-only" in ids

    def test_falls_back_to_transcript_when_history_display_is_skippable(
        self, fake_claude_home, sessions_dir, project_cwd
    ):
        # history.jsonl carries "/exit" as the first display for this
        # session, but the transcript has the user's real prompt earlier
        # in the same conversation. Both pickers should converge on the
        # real prompt — that's the whole point of issue #181.
        session_id = "abc12345"
        jsonl_path = sessions_dir / f"{session_id}.jsonl"
        _write_jsonl(
            jsonl_path,
            [
                _user_line(session_id, "Plot the closing prices for AAPL"),
                _assistant_line(session_id),
                _user_line(session_id, "/exit"),
            ],
        )

        _write_history(
            fake_claude_home,
            [_history_line(session_id, project_cwd, 1_700_000_000_000, "/exit")],
        )

        result = list_all_sessions(cwd=project_cwd, claude_home=str(fake_claude_home))
        match = next(s for s in result if s.session_id == session_id)
        assert match.preview == "Plot the closing prices for AAPL"

    def test_empty_preview_when_display_and_transcript_both_skippable(
        self, fake_claude_home, sessions_dir, project_cwd
    ):
        # Session whose history.jsonl display AND transcript are both
        # skippable is still resumable, so it's listed — but with an empty
        # preview. The picker UI relies on the session id + timestamp meta
        # row instead of rendering a literal "/exit" line (issue #187).
        session_id = "barren12"
        jsonl_path = sessions_dir / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, [_user_line(session_id, "/clear")])
        _write_history(
            fake_claude_home,
            [_history_line(session_id, project_cwd, 1_700_000_000_000, "/exit")],
        )

        result = list_all_sessions(cwd=project_cwd, claude_home=str(fake_claude_home))
        match = next(s for s in result if s.session_id == session_id)
        assert match.preview == ""

    def test_transcript_is_authoritative_for_preview(
        self, fake_claude_home, sessions_dir, project_cwd
    ):
        # The transcript on disk is now the source of truth for the
        # preview. history.jsonl can drift (Claude Code skipped writing
        # it for some flows), so listing relies on what's actually in the
        # transcript file. If history.jsonl says one thing and the
        # transcript says another, the transcript wins.
        session_id = "good1234"
        jsonl_path = sessions_dir / f"{session_id}.jsonl"
        _write_jsonl(
            jsonl_path,
            [_user_line(session_id, "transcript-recorded text", cwd=project_cwd)],
        )

        _write_history(
            fake_claude_home,
            [
                _history_line(
                    session_id,
                    project_cwd,
                    1_700_000_000_000,
                    "stale history display",
                )
            ],
        )

        result = list_all_sessions(cwd=project_cwd, claude_home=str(fake_claude_home))
        match = next(s for s in result if s.session_id == session_id)
        assert match.preview == "transcript-recorded text"

    def test_deduplicates_sessions_in_both_sources(
        self, fake_claude_home, sessions_dir, project_cwd
    ):
        session_id = "shared"
        jsonl_path = sessions_dir / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, [_user_line(session_id, "shared session")])

        _write_history(
            fake_claude_home,
            [_history_line(session_id, project_cwd, 1_000_000_000_000, "shared session")],
        )

        result = list_all_sessions(cwd=project_cwd, claude_home=str(fake_claude_home))
        assert len([s for s in result if s.session_id == session_id]) == 1

    @pytest.mark.parametrize(
        "skippable_display",
        [
            "Additional context: Current directory open in Jupyter is: '/x'",
            "<local-command-caveat>Caveat: ...</local-command-caveat>",
            "<command-name>/clear</command-name>",
            "[Request interrupted by user for tool use]",
            "Unknown slash command: clear",
            "Unknown skill: clear",
            "/exit",
        ],
        ids=[
            "nbi_context_preamble",
            "local_command_envelope",
            "command_envelope",
            "request_interrupted",
            "unknown_slash_echo",
            "unknown_skill_echo",
            "control_verb",
        ],
    )
    def test_chat_picker_and_launcher_show_same_preview_for_issue_181(
        self, fake_claude_home, sessions_dir, project_cwd, skippable_display
    ):
        # Reproduces issue #181: same session id, two pickers, different
        # previews. Both pickers must converge on the same string when the
        # session's history.jsonl display falls into ANY skip category.
        session_id = "issue181"
        jsonl_path = sessions_dir / f"{session_id}.jsonl"
        _write_jsonl(
            jsonl_path,
            [
                _user_line(session_id, "Plot the closing prices for AAPL"),
                _assistant_line(session_id),
                _user_line(session_id, skippable_display),
            ],
        )
        _write_history(
            fake_claude_home,
            [_history_line(session_id, project_cwd, 1_700_000_000_000, skippable_display)],
        )

        chat_picker_session = next(
            s
            for s in _list_sessions_in_dir(project_cwd, claude_home=str(fake_claude_home))
            if s.session_id == session_id
        )
        launcher_session = next(
            s
            for s in list_all_sessions(cwd=project_cwd, claude_home=str(fake_claude_home))
            if s.session_id == session_id
        )

        assert chat_picker_session.preview == launcher_session.preview
        assert chat_picker_session.preview == "Plot the closing prices for AAPL"


class TestCrossSurfaceConsistency:
    """Pin that NBI's session-listing surfaces converge on the same
    on-disk set ``claude --resume`` consumes.

    Three surfaces care about session enumeration: the chat sidebar's
    Resume button (scope=cwd), the Launcher tile picker (scope=all), and
    Claude Code's own ``/resume`` (external; not shelled out by these
    tests). The authoritative ground truth all three share is the set
    of ``.jsonl`` transcripts under ``~/.claude/projects/*/``. These
    tests assert that NBI's two listing paths enumerate that set, so a
    user can't see a session in one surface and not the other. Whether
    Claude Code's own ``/resume`` enumerates the same set is its
    contract to keep, not ours; a Galata or shell-out integration test
    that runs ``claude --resume`` and diffs IDs against ours is the
    cross-binary check, deferred to follow-up.
    """

    def test_launcher_returns_every_on_disk_session(
        self, fake_claude_home, project_cwd, tmp_path
    ):
        # Three projects, each with a session. The launcher (scope=all)
        # must enumerate all three regardless of whether history.jsonl
        # exists or names them.
        proj_a = project_cwd
        proj_b = str(tmp_path / "projects" / "second-project")
        proj_c = str(tmp_path / "projects" / "third-project")
        Path(proj_b).mkdir(parents=True)
        Path(proj_c).mkdir(parents=True)

        for sid, cwd in [
            ("a-sess", proj_a),
            ("b-sess", proj_b),
            ("c-sess", proj_c),
        ]:
            sdir = get_sessions_dir(cwd, claude_home=str(fake_claude_home))
            sdir.mkdir(parents=True, exist_ok=True)
            _write_jsonl(sdir / f"{sid}.jsonl", [_user_line(sid, sid, cwd=cwd)])

        result = list_all_sessions(claude_home=str(fake_claude_home))
        ids = {s.session_id for s in result}
        assert ids == {"a-sess", "b-sess", "c-sess"}

    def test_launcher_finds_sessions_without_history_jsonl(
        self, fake_claude_home, project_cwd
    ):
        # /resume inside Claude works whether or not history.jsonl exists,
        # so the launcher must too. This is the user-reported bug: empty
        # or stale history.jsonl made cross-project sessions disappear
        # from the launcher tile.
        sdir = get_sessions_dir(project_cwd, claude_home=str(fake_claude_home))
        sdir.mkdir(parents=True)
        _write_jsonl(
            sdir / "abc.jsonl",
            [_user_line("abc", "Find me later", cwd=project_cwd)],
        )

        # No history.jsonl on disk at all.
        result = list_all_sessions(claude_home=str(fake_claude_home))
        assert {s.session_id for s in result} == {"abc"}

    def test_cwd_scope_is_subset_of_all_scope(
        self, fake_claude_home, project_cwd, tmp_path
    ):
        # Whatever the chat-sidebar (cwd-scoped) shows must be a subset of
        # what the launcher (all-scoped) shows. This is the structural
        # invariant we never want to violate, regardless of how the picker
        # filters internally.
        other_cwd = str(tmp_path / "projects" / "elsewhere")
        Path(other_cwd).mkdir(parents=True)

        my_dir = get_sessions_dir(project_cwd, claude_home=str(fake_claude_home))
        my_dir.mkdir(parents=True)
        _write_jsonl(
            my_dir / "mine.jsonl",
            [_user_line("mine", "in my project", cwd=project_cwd)],
        )

        other_dir = get_sessions_dir(other_cwd, claude_home=str(fake_claude_home))
        other_dir.mkdir(parents=True)
        _write_jsonl(
            other_dir / "theirs.jsonl",
            [_user_line("theirs", "in another project", cwd=other_cwd)],
        )

        all_sessions = list_all_sessions(
            cwd=project_cwd, claude_home=str(fake_claude_home)
        )
        cwd_only = [
            s
            for s in all_sessions
            if os.path.realpath(s.cwd) == os.path.realpath(project_cwd)
        ]
        all_ids = {s.session_id for s in all_sessions}
        cwd_ids = {s.session_id for s in cwd_only}
        assert cwd_ids.issubset(all_ids)
        assert cwd_ids == {"mine"}
        assert all_ids == {"mine", "theirs"}

    def test_cross_project_session_carries_its_cwd_for_resume(
        self, fake_claude_home, tmp_path
    ):
        # The launcher tile resumes cross-project sessions by issuing
        # `cd ${session.cwd} && claude --resume <id>` in a new terminal.
        # That only works if the cwd field is populated AND accurate.
        # Pin: every session returned by the project-walk carries the
        # transcript-recorded cwd.
        proj = str(tmp_path / "projects" / "real-project")
        Path(proj).mkdir(parents=True)
        sdir = get_sessions_dir(proj, claude_home=str(fake_claude_home))
        sdir.mkdir(parents=True)
        _write_jsonl(
            sdir / "sess.jsonl",
            [_user_line("sess", "prompt", cwd=proj)],
        )

        result = list_all_sessions(claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].cwd == proj

    def test_dash_decoded_cwd_fallback_when_transcript_omits_cwd(
        self, fake_claude_home
    ):
        # Older transcripts (and synthetic test fixtures) may not carry a
        # cwd field. The dash-decoded directory name is the fallback. The
        # decoding is lossy for paths with literal dashes — pin the
        # mechanical behavior of the fallback (dashes -> slashes,
        # leading-dash -> root slash) so a regression in the decoder is
        # surfaced immediately.
        encoded_dir_name = "-Users-someone-clean"
        sdir = fake_claude_home / "projects" / encoded_dir_name
        sdir.mkdir(parents=True)
        _write_jsonl(
            sdir / "sess.jsonl",
            # No cwd in the line — exercises the fallback path.
            [_user_line("sess", "prompt")],
        )

        result = list_all_sessions(claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].cwd == "/Users/someone/clean"

    def test_mtime_cache_skips_reparse_on_unchanged_file(
        self, fake_claude_home, sessions_dir, project_cwd, monkeypatch
    ):
        # The project-walk reads every .jsonl on every call by default
        # (D207). We cache parse results by (path, mtime) so a no-op
        # refresh doesn't re-open files. Pin: a second list call doesn't
        # invoke the underlying reader for unchanged transcripts.
        from notebook_intelligence import claude_sessions

        _write_jsonl(
            sessions_dir / "cached.jsonl",
            [_user_line("cached", "prompt", cwd=project_cwd)],
        )

        first = list_all_sessions(claude_home=str(fake_claude_home))
        assert len(first) == 1

        # Wrap _read_session_info to count calls on the second pass.
        call_count = {"n": 0}
        real_reader = claude_sessions._read_session_info

        def counting_reader(path):
            call_count["n"] += 1
            return real_reader(path)

        monkeypatch.setattr(
            claude_sessions, "_read_session_info", counting_reader
        )

        second = list_all_sessions(claude_home=str(fake_claude_home))
        assert len(second) == 1
        assert call_count["n"] == 0  # served from cache


class TestClaudeConfigDirDefault:
    """The claude_home default must follow CLAUDE_CONFIG_DIR (issue #373).

    The CLI writes transcripts under $CLAUDE_CONFIG_DIR/projects when the
    env var is set; the handler calls list_all_sessions without a
    claude_home, so the default is what production traffic exercises.
    """

    def test_get_sessions_dir_honors_claude_config_dir(
        self, monkeypatch, tmp_path
    ):
        override = tmp_path / "workspace" / ".claude"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(override))
        result = get_sessions_dir("/some/cwd")
        assert result == override / "projects" / encode_cwd("/some/cwd")

    def test_get_sessions_dir_defaults_to_home_claude(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        result = get_sessions_dir("/some/cwd")
        assert result == tmp_path / ".claude" / "projects" / encode_cwd(
            "/some/cwd"
        )

    def test_list_all_sessions_reads_claude_config_dir(
        self, monkeypatch, tmp_path
    ):
        override = tmp_path / "workspace" / ".claude"
        cwd = str(tmp_path / "proj")
        _write_jsonl(
            override / "projects" / encode_cwd(cwd) / "abc.jsonl",
            [_user_line("abc", "hello from the override dir", cwd=cwd)],
        )
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(override))

        sessions = list_all_sessions()

        assert [s.session_id for s in sessions] == ["abc"]
        assert sessions[0].preview == "hello from the override dir"

    def test_list_all_sessions_ignores_home_claude_when_overridden(
        self, monkeypatch, tmp_path
    ):
        home = tmp_path / "home"
        cwd = str(tmp_path / "proj")
        _write_jsonl(
            home / ".claude" / "projects" / encode_cwd(cwd) / "old.jsonl",
            [_user_line("old", "stale home transcript", cwd=cwd)],
        )
        override = tmp_path / "workspace" / ".claude"
        override.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(override))

        assert list_all_sessions() == []
