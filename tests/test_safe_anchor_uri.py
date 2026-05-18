# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Tests for ``notebook_intelligence.util.safe_anchor_uri``.

Anchor parts are streamed from arbitrary LLM/tool output and rendered as
``<a href={uri} target="_blank">`` in the chat sidebar. React does not block
``javascript:`` / ``data:`` / ``vbscript:`` schemes in href attributes, and
``rel="noopener"`` does not prevent ``javascript:`` execution against the
parent origin. The helper rejects everything outside a tight scheme
allowlist so a malicious tool result cannot turn a chat link into a
same-origin script-execution sink against the Jupyter server.
"""

import pytest

from notebook_intelligence.util import safe_anchor_uri


class TestSafeAnchorUriAllowed:
    def test_https(self):
        assert safe_anchor_uri("https://example.com/page") == "https://example.com/page"

    def test_http(self):
        assert safe_anchor_uri("http://example.com/") == "http://example.com/"

    def test_mailto(self):
        assert safe_anchor_uri("mailto:bob@example.com") == "mailto:bob@example.com"

    def test_scheme_match_is_case_insensitive(self):
        assert safe_anchor_uri("HTTPS://Example.COM/Path") == "HTTPS://Example.COM/Path"

    def test_trims_surrounding_whitespace(self):
        assert safe_anchor_uri("   https://example.com/   ") == "https://example.com/"


class TestSafeAnchorUriRejected:
    @pytest.mark.parametrize(
        "uri",
        [
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "blob:https://example.com/abc",
            "about:blank",
            "chrome://settings",
        ],
    )
    def test_dangerous_schemes(self, uri):
        assert safe_anchor_uri(uri) == ""

    @pytest.mark.parametrize(
        "uri",
        [
            "java\tscript:alert(1)",
            "javascript\n:alert(1)",
            "java\x00script:alert(1)",
            "javascript:\x07alert(1)",
        ],
    )
    def test_c0_control_characters(self, uri):
        # Some browsers strip C0 / DEL controls before parsing the URL,
        # which would unmask a forbidden scheme. Reject anything containing
        # them so the allowlist check sees the original scheme.
        assert safe_anchor_uri(uri) == ""

    @pytest.mark.parametrize(
        "uri",
        [
            "https://example.com/\x85",          # NEL
            "https://example.com/\xa0",          # NBSP
            "https://example.com/ ",        # LINE SEPARATOR
            "https://example.com/ ",        # PARA SEPARATOR
            "https://example.com/﻿",        # BOM
            "https://example.com/​",        # ZERO WIDTH SPACE
            "https://example.com/‎",        # LRM
            "https://example.com/‮",        # RLO
            "https://example.com/⁦",        # LRI
            "https://example.com/",        # C1
        ],
    )
    def test_unicode_format_marks_rejected(self, uri):
        # Defense in depth: zero-width / bidi / format marks can visually
        # impersonate a URL even when they don't unmask a scheme. Reject so
        # the rendered title never silently differs from the resolved href.
        assert safe_anchor_uri(uri) == ""

    @pytest.mark.parametrize(
        "uri",
        [
            "/api/contents/secret.json",
            "../etc/passwd",
            "./foo",
            "#section",
            "foo.txt",
        ],
    )
    def test_relative_and_bare_paths(self, uri):
        # The allowlist is scheme-only. Relative paths and bare filenames
        # are dropped; first-party code does not construct AnchorData and
        # tool output should produce absolute http(s)/mailto links.
        assert safe_anchor_uri(uri) == ""

    @pytest.mark.parametrize(
        "uri",
        ["", "   ", "\t\n", None, 0, b"https://example.com/"],
    )
    def test_empty_and_non_string(self, uri):
        assert safe_anchor_uri(uri) == ""

    def test_rejects_crlf_inside_uri(self):
        # CRLF inside an otherwise valid URI is a classic
        # log-injection / header-splitting shape and falls in the C0
        # range. Pin explicitly so a future refactor that switches to a
        # regex-only check can't silently regress.
        assert safe_anchor_uri("https://example.com/\r\nfoo") == ""
        assert safe_anchor_uri("https://example.com/\nfoo") == ""

    def test_rejects_excessive_length(self):
        # A URI longer than the cap is almost certainly hostile or
        # malformed, and scanning the whole thing twice on every chat
        # render is wasted work.
        long_path = "x" * 8200
        assert safe_anchor_uri(f"https://example.com/{long_path}") == ""

    def test_accepts_uri_near_length_cap(self):
        # Just under the cap should still pass. Pins that the cap is an
        # outer bound, not an arbitrarily-tight one.
        long_path = "x" * 8000
        uri = f"https://example.com/{long_path}"
        assert safe_anchor_uri(uri) == uri
