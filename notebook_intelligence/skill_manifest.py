"""Loads managed-skills manifests (YAML/JSON) from URLs or local file paths.

A single manifest describes the set of Claude skills that should be installed
on this notebook. See the README for the schema; briefly:

    skills:
      - url: https://github.com/org/repo/tree/main/skills/data-eda
        name: data-eda        # optional override of the installed skill name
        scope: user           # optional, "user" or "project" (default "user")

A deployment can also point at multiple manifests at once (comma-separated in
``NBI_SKILLS_MANIFEST`` or the matching traitlet). ``load_manifests`` merges
them, dedupes by URL and by predicted installed-name, and reports per-source
fetch failures without aborting the whole reconcile.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

from notebook_intelligence.skill_github_import import (
    _slug as _slug_skill_name,
    parse_github_url,
)
from notebook_intelligence.util import resolve_github_token, split_csv as _split_csv
from notebook_intelligence.skillset import SKILL_NAME_PATTERN

log = logging.getLogger(__name__)

MAX_MANIFEST_BYTES = 1 * 1024 * 1024  # 1 MB
FETCH_TIMEOUT_SECONDS = 15.0
_VALID_SCOPES = ("user", "project")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_GITHUB_HOSTS = (
    "github.com",
    "www.github.com",
    "api.github.com",
    "raw.githubusercontent.com",
)


def _is_github_host(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except ValueError:
        return False
    return host in _GITHUB_HOSTS or host.endswith(".githubusercontent.com")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse any 30x on a manifest fetch.

    The manifest URL is provided by the deployment operator and points to a
    static config file. A redirect here would mean the operator's URL is
    out-of-date or — worse — that something on the network is rewriting the
    request. Either way, silently following along risks shipping a bearer
    token to an unintended host or installing skills from a substituted
    manifest. Surface it as an error and let the operator fix the URL.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            f"Refusing redirect on manifest fetch (to {newurl})",
            headers,
            fp,
        )


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def _urlopen_no_redirect(req, timeout):
    """Open a manifest URL without following redirects (test seam)."""
    return _NO_REDIRECT_OPENER.open(req, timeout=timeout)


class ManifestError(ValueError):
    """Raised when a manifest cannot be loaded or fails validation."""


@dataclass
class ManifestEntry:
    url: str
    name: Optional[str] = None
    scope: str = "user"
    # Manifest URL/path this entry came from. Populated by ``load_manifests``
    # so dedupe warnings can name both the kept and the ignored manifest.
    # Empty string means "unknown" (single-manifest legacy path).
    source: str = ""


@dataclass
class SkillsManifest:
    entries: List[ManifestEntry]


@dataclass
class MergedManifest:
    """Output of ``load_manifests``: deduped entries plus per-source diagnostics.

    ``errors`` carries fatal failures (a manifest source could not be fetched
    or parsed) so the reconciler can skip stale-removal that cycle. ``warnings``
    carries advisory notes (cross-manifest URL dupes) that don't disturb
    reconciliation but should reach the operator.
    ``loaded_sources`` records the sources that successfully loaded, which the
    reconciler uses to decide whether stale removal is safe.
    """
    manifest: SkillsManifest
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    loaded_sources: List[str] = field(default_factory=list)


def load_manifest(source: str, *, token: Optional[str] = None) -> SkillsManifest:
    """Load and validate a manifest from a URL or local filesystem path.

    URLs use `Authorization: Bearer {token}` when token is provided; useful for
    manifests hosted on private GitHub repos via raw.githubusercontent.com.
    """
    if not isinstance(source, str) or not source.strip():
        raise ManifestError("Manifest source is empty")
    source = source.strip()

    raw = _read_source(source, token=token)
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ManifestError(f"Manifest is not valid YAML/JSON: {e}")

    if not isinstance(parsed, dict):
        raise ManifestError("Manifest root must be a mapping")
    raw_entries = parsed.get("skills")
    if raw_entries is None:
        raise ManifestError("Manifest must have a top-level 'skills' list")
    if not isinstance(raw_entries, list):
        raise ManifestError("'skills' must be a list")

    entries: List[ManifestEntry] = []
    for idx, item in enumerate(raw_entries):
        entry = _parse_entry(item, idx)
        entry.source = source
        entries.append(entry)

    return SkillsManifest(entries=entries)


def split_sources(raw: str) -> List[str]:
    """Split a comma-separated list of manifest sources.

    Empty input or all-whitespace input → empty list. URLs containing
    literal commas are not supported and will split; the operator should
    rename/relocate such manifests. Thin shim over the shared
    ``util.split_csv`` so the wire-format contract stays consistent with
    the rest of NBI's comma-separated env vars.
    """
    return _split_csv(raw)


def _predicted_name(entry: ManifestEntry) -> Optional[str]:
    """Best-effort prediction of the on-disk skill name for dedupe.

    Mirrors the slug + fallback rules that the real installer applies in
    ``skill_github_import._derive_name`` (without the frontmatter step —
    that requires fetching the bundle). The slug step is load-bearing:
    a path like ``.../tree/main/Data EDA`` installs as ``data-eda`` and
    must dedupe against an explicit ``name: data-eda`` entry from
    another manifest.

    Returns ``None`` for non-GitHub URLs so the caller can warn about
    the dropped dedupe; the eventual install-time collision will still
    surface as an error, but the operator deserves a heads-up.
    """
    if entry.name:
        return _slug_skill_name(entry.name)
    try:
        info = parse_github_url(entry.url)
    except ValueError:
        return None
    raw = info.subpath.rstrip("/").rsplit("/", 1)[-1] if info.subpath else ""
    candidate = _slug_skill_name(raw) if raw else ""
    if not candidate:
        candidate = _slug_skill_name(info.repo)
    return candidate or None


def load_manifests(
    sources: List[str], *, token: Optional[str] = None
) -> MergedManifest:
    """Load and merge multiple manifests, deduping entries across sources.

    Dedupe semantics:

    - **By URL**: if two sources list the same ``url:``, the earlier source
      wins and a warning names both manifests so the operator can fix one
      of them. The reconciler keeps progressing.
    - **By installed name**: if two entries from different URLs would resolve
      to the same on-disk skill name, the second is dropped with an entry in
      ``errors`` so the install layer never sees the collision. Predicted
      from ``entry.name`` if set, otherwise from the URL's last subpath
      segment.

    Partial failure: each source loads independently. A failed source becomes
    an entry in ``errors`` and excludes itself from ``loaded_sources``. The
    successful sources still contribute entries so a transient outage on one
    manifest doesn't stop the rest.
    """
    if not sources:
        return MergedManifest(manifest=SkillsManifest(entries=[]))

    merged: List[ManifestEntry] = []
    errors: List[str] = []
    warnings: List[str] = []
    loaded_sources: List[str] = []
    seen_urls: dict = {}  # url -> source it was first seen in
    seen_names: dict = {}  # predicted name -> (source, url) it was first seen in

    for source in sources:
        try:
            loaded = load_manifest(source, token=token)
        except ManifestError as exc:
            errors.append(f"{source}: {exc}")
            continue
        loaded_sources.append(source)
        for entry in loaded.entries:
            if entry.url in seen_urls:
                first_source = seen_urls[entry.url]
                warnings.append(
                    f"skills_manifest dupe: {entry.url!r} first seen in "
                    f"{first_source!r}, ignored in {source!r}"
                )
                continue
            seen_urls[entry.url] = source
            predicted = _predicted_name(entry)
            if predicted is None:
                # Non-GitHub URL or unparseable. Cross-manifest name dedupe
                # can't run for this entry; the install-time collision check
                # in SkillManager is the only remaining guard.
                warnings.append(
                    f"skills_manifest: cannot predict installed name for "
                    f"{entry.url!r} ({source!r}); cross-manifest name "
                    f"dedupe skipped for this entry"
                )
                merged.append(entry)
                continue
            if predicted in seen_names:
                first_source, first_url = seen_names[predicted]
                errors.append(
                    f"skill {predicted!r}: name collision; first installed "
                    f"from {first_url!r} ({first_source!r}), skipped "
                    f"{entry.url!r} ({source!r})"
                )
                continue
            seen_names[predicted] = (source, entry.url)
            merged.append(entry)

    return MergedManifest(
        manifest=SkillsManifest(entries=merged),
        errors=errors,
        warnings=warnings,
        loaded_sources=loaded_sources,
    )


def _parse_entry(item, index: int) -> ManifestEntry:
    if not isinstance(item, dict):
        raise ManifestError(f"skills[{index}] must be a mapping")
    url = item.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ManifestError(f"skills[{index}].url is required")

    name = item.get("name")
    if name is not None:
        if not isinstance(name, str) or not SKILL_NAME_PATTERN.match(name):
            raise ManifestError(
                f"skills[{index}].name '{name}' is not a valid skill name"
            )

    scope = item.get("scope", "user")
    if scope not in _VALID_SCOPES:
        raise ManifestError(
            f"skills[{index}].scope must be one of {_VALID_SCOPES}, got {scope!r}"
        )

    return ManifestEntry(url=url.strip(), name=name, scope=scope)


def _read_source(source: str, *, token: Optional[str]) -> str:
    if _URL_RE.match(source):
        return _fetch_url(source, token=token)
    # Treat as a filesystem path (e.g., k8s ConfigMap mount).
    path = Path(source).expanduser()
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise ManifestError(f"Manifest file not found: {source}")
    except OSError as e:
        raise ManifestError(f"Could not read manifest file {source}: {e}")
    if len(data) > MAX_MANIFEST_BYTES:
        raise ManifestError(
            f"Manifest file exceeds {MAX_MANIFEST_BYTES} bytes"
        )
    return data.decode("utf-8", errors="replace")


def _fetch_url(url: str, *, token: Optional[str]) -> str:
    headers = {
        "User-Agent": "notebook-intelligence-skills-manifest",
        "Accept": "application/x-yaml, application/json, text/plain, */*",
    }
    # Explicit NBI_MANAGED_SKILLS_TOKEN wins. Otherwise, for github-hosted
    # manifests, fall back to the same GITHUB_TOKEN / GH_TOKEN / `gh auth token`
    # chain used for fetching skill tarballs — private-repo manifests should
    # just work when the user already has a GitHub login.
    effective_token = token
    if not effective_token and _is_github_host(url):
        effective_token = resolve_github_token()
    if effective_token:
        headers["Authorization"] = f"Bearer {effective_token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with _urlopen_no_redirect(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            data = resp.read(MAX_MANIFEST_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise ManifestError(f"Manifest fetch failed (HTTP {e.code}): {e.reason}")
    except urllib.error.URLError as e:
        raise ManifestError(f"Could not reach manifest URL {url}: {e.reason}")
    if len(data) > MAX_MANIFEST_BYTES:
        raise ManifestError(
            f"Manifest at {url} exceeds {MAX_MANIFEST_BYTES} bytes"
        )
    return data.decode("utf-8", errors="replace")
