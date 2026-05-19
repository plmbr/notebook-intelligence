import logging
import shutil
import threading
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

from notebook_intelligence.skillset import (
    SKILL_ENTRY_FILE,
    SKILL_NAME_PATTERN,
    SKILL_NAME_REQUIREMENT,
    Skill,
    SkillScope,
    serialize_skill_md,
)
from notebook_intelligence.skill_github_import import (
    parse_github_url,
    resolve_desired_sha,
    stage_skill_from_github,
)

log = logging.getLogger(__name__)


class SkillManager:
    """Discovers, creates, updates, and deletes Claude skills in user and project scopes."""

    WATCH_INTERVAL_SECONDS = 2.0

    def __init__(self, user_dir: Path, project_dir: Path):
        self._scope_dirs: Dict[SkillScope, Path] = {
            "user": Path(user_dir),
            "project": Path(project_dir),
        }
        self._listeners: List[Callable[[], None]] = []
        self._listeners_lock = threading.Lock()
        self._last_signature: tuple = ()
        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_stop = threading.Event()

    def scope_dir(self, scope: SkillScope) -> Path:
        if scope not in self._scope_dirs:
            raise ValueError(f"Unknown scope: {scope}")
        return self._scope_dirs[scope]

    def on_skills_changed(self, listener: Callable[[], None]) -> None:
        with self._listeners_lock:
            self._listeners.append(listener)

    def _notify_skills_changed(self) -> None:
        # Suppress the next watcher-driven fire so self-triggered mutations don't double-notify.
        self._last_signature = self._compute_signature()
        with self._listeners_lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener()
            except Exception as e:
                log.error(f"Skill change listener raised: {e}")

    def start_watching(self) -> None:
        if self._watcher_thread is not None:
            return
        self._watcher_stop.clear()
        # Baseline is computed on the watcher thread to avoid blocking startup.
        self._last_signature = ()
        self._watcher_thread = threading.Thread(
            name="Skill Watcher",
            target=self._watch_loop,
            daemon=True,
        )
        self._watcher_thread.start()

    def stop_watching(self, timeout: float = 5.0) -> None:
        thread = self._watcher_thread
        self._watcher_stop.set()
        if thread is not None:
            thread.join(timeout=timeout)
        self._watcher_thread = None

    def _watch_loop(self) -> None:
        self._last_signature = self._compute_signature()
        while not self._watcher_stop.wait(self.WATCH_INTERVAL_SECONDS):
            current = self._compute_signature()
            if current != self._last_signature:
                self._last_signature = current
                log.info("Skill directory change detected; notifying listeners")
                self._notify_skills_changed()

    def _iter_bundle_dirs(self, scope_dir: Path) -> Iterator[Path]:
        """Yield bundle dirs (each containing a SKILL.md) inside ``scope_dir``.

        Hidden entries (``.git``, ``.DS_Store``, etc.) are skipped — see
        ``_compute_signature`` for why this matters for change detection.
        Errors from ``iterdir`` are swallowed so a transient FS hiccup
        doesn't tear down the watcher thread.
        """
        if not scope_dir.exists():
            return
        try:
            entries = sorted(scope_dir.iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith('.'):
                continue
            if (entry / SKILL_ENTRY_FILE).exists():
                yield entry

    def _compute_signature(self) -> tuple:
        """Return a structural snapshot used to detect skill-content changes.

        For each scope, includes the sorted bundle-name + bundle-dir mtime +
        SKILL.md mtime triples. Crucially, this skips:

        * The scope directory's own mtime — siblings like ``.DS_Store`` (macOS
          Finder), ``.git/`` operations on a parent, or unrelated lockfiles
          would otherwise bump the parent's mtime and trip the watcher
          despite no actual skill change. ``#208`` was this case: launching
          ``claude`` in a terminal touched a sibling under
          ``~/.claude/skills/`` and the watcher fired a "Skills reloaded"
          banner the user hadn't asked for.
        * Hidden entries (``.git``, ``.DS_Store``, etc.) inside the scope —
          same reasoning.

        Bundle-dir mtime is preserved so helper-file edits inside a bundle
        still register as a change. Equality (not ``>``) drives the
        watcher's decision so renames + deletions are detected too.
        """
        parts = []
        for scope, scope_dir in sorted(self._scope_dirs.items()):
            bundles = []
            for entry in self._iter_bundle_dirs(scope_dir):
                try:
                    bundles.append(
                        (
                            entry.name,
                            entry.stat().st_mtime,
                            (entry / SKILL_ENTRY_FILE).stat().st_mtime,
                        )
                    )
                except OSError:
                    continue
            parts.append((scope, tuple(bundles)))
        return tuple(parts)

    def list_skills(self) -> List[Skill]:
        skills: List[Skill] = []
        for scope, scope_dir in self._scope_dirs.items():
            for entry in self._iter_bundle_dirs(scope_dir):
                try:
                    skills.append(Skill.from_path(entry, scope))
                except Exception as e:
                    log.error(f"Failed to load skill from {entry}: {e}")
        skills.sort(key=lambda s: (s.scope, s.name))
        return skills

    def _locate_skill_path(self, scope: SkillScope, name: str) -> Optional[Path]:
        """Return the bundle dir for a skill, or None if it doesn't exist."""
        # Validate before concatenating into a path — blocks "../" and similar traversal.
        _validate_name(name)
        bundle_dir = self.scope_dir(scope) / name
        if bundle_dir.is_dir() and (bundle_dir / SKILL_ENTRY_FILE).exists():
            return bundle_dir
        return None

    def get_skill(self, scope: SkillScope, name: str) -> Optional[Skill]:
        _validate_name(name)
        path = self._locate_skill_path(scope, name)
        if path is None:
            return None
        try:
            return Skill.from_path(path, scope)
        except Exception as e:
            log.error(f"Failed to load skill from {path}: {e}")
            return None

    def create_skill(
        self,
        scope: SkillScope,
        name: str,
        description: str,
        allowed_tools: List[str],
        body: str,
    ) -> Skill:
        _validate_name(name)

        scope_dir = self.scope_dir(scope)
        scope_dir.mkdir(parents=True, exist_ok=True)

        if self._locate_skill_path(scope, name) is not None:
            raise ValueError(f"Skill '{name}' already exists in {scope} scope")

        bundle_dir = scope_dir / name
        bundle_dir.mkdir(parents=True, exist_ok=False)
        md_content = serialize_skill_md(name, description, allowed_tools, body)
        (bundle_dir / SKILL_ENTRY_FILE).write_text(md_content, encoding="utf-8")
        skill = Skill.from_path(bundle_dir, scope)

        self._notify_skills_changed()
        return skill

    def update_skill(
        self,
        scope: SkillScope,
        name: str,
        description: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None,
        body: Optional[str] = None,
        tracks_upstream: Optional[bool] = None,
    ) -> Skill:
        skill = self.get_skill(scope, name)
        if skill is None:
            raise FileNotFoundError(f"Skill '{name}' not found in {scope} scope")

        new_description = description if description is not None else skill.description
        new_allowed_tools = allowed_tools if allowed_tools is not None else skill.allowed_tools
        new_body = body if body is not None else skill.body

        # `tracks_upstream=None` means "leave unchanged" — caller didn't touch
        # the toggle. Explicit True/False both apply. Managed skills cannot
        # opt into tracking; the two metadata pairs are mutually exclusive.
        if tracks_upstream is None:
            new_tracks_upstream = skill.tracks_upstream
        else:
            if tracks_upstream and skill.managed:
                raise ValueError(
                    "Managed skills cannot track upstream; remove from the "
                    "manifest first."
                )
            if tracks_upstream and not skill.source:
                raise ValueError(
                    f"Skill '{name}' has no recorded source URL; can only "
                    "track upstream for GitHub-imported skills."
                )
            new_tracks_upstream = bool(tracks_upstream)
        # Toggling off clears tracking_ref so a future re-opt-in starts
        # from a clean slate; the existing bundle on disk is otherwise
        # untouched and becomes a plain user-authored skill again.
        new_tracking_ref = skill.tracking_ref if new_tracks_upstream else ""

        md_content = serialize_skill_md(
            name,
            new_description,
            new_allowed_tools,
            new_body,
            source=skill.source,
            managed_source=skill.managed_source,
            managed_ref=skill.managed_ref,
            tracks_upstream=new_tracks_upstream,
            tracking_ref=new_tracking_ref,
        )
        skill.skill_md_path().write_text(md_content, encoding="utf-8")

        # Construct the updated Skill in-memory rather than re-reading + re-parsing from disk:
        # we just wrote the file, so we already know every field it will contain.
        updated = Skill(
            name=name,
            scope=scope,
            root_path=skill.root_path,
            description=new_description,
            allowed_tools=list(new_allowed_tools),
            body=new_body,
            source=skill.source,
            managed_source=skill.managed_source,
            managed_ref=skill.managed_ref,
            tracks_upstream=new_tracks_upstream,
            tracking_ref=new_tracking_ref,
        )
        self._notify_skills_changed()
        return updated

    def rename_skill(self, scope: SkillScope, old_name: str, new_name: str) -> Skill:
        _validate_name(old_name)
        _validate_name(new_name)
        skill = self.get_skill(scope, old_name)
        if skill is None:
            raise FileNotFoundError(f"Skill '{old_name}' not found in {scope} scope")
        if old_name == new_name:
            return skill

        scope_dir = self.scope_dir(scope)
        new_bundle_dir = scope_dir / new_name
        if new_bundle_dir.exists():
            raise FileExistsError(f"Skill '{new_name}' already exists in {scope} scope")

        skill.root_path.rename(new_bundle_dir)
        # Rewrite SKILL.md so its `name:` frontmatter matches the new directory name.
        # Claude uses the frontmatter name, not the directory, to identify the skill.
        md_content = serialize_skill_md(
            new_name,
            skill.description,
            skill.allowed_tools,
            skill.body,
            source=skill.source,
            managed_source=skill.managed_source,
            managed_ref=skill.managed_ref,
            tracks_upstream=skill.tracks_upstream,
            tracking_ref=skill.tracking_ref,
        )
        (new_bundle_dir / SKILL_ENTRY_FILE).write_text(md_content, encoding="utf-8")

        renamed = Skill.from_path(new_bundle_dir, scope)
        self._notify_skills_changed()
        return renamed

    def delete_skill(self, scope: SkillScope, name: str) -> None:
        _validate_name(name)
        path = self._locate_skill_path(scope, name)
        if path is None:
            raise FileNotFoundError(f"Skill '{name}' not found in {scope} scope")
        shutil.rmtree(path)
        self._notify_skills_changed()

    def _require_bundle(self, scope: SkillScope, name: str) -> Skill:
        _validate_name(name)
        scope_dir = self.scope_dir(scope)
        bundle_dir = scope_dir / name
        if not (bundle_dir.is_dir() and (bundle_dir / SKILL_ENTRY_FILE).exists()):
            raise FileNotFoundError(f"Bundle skill '{name}' not found in {scope} scope")
        return Skill.from_path(bundle_dir, scope)

    def read_bundle_file(self, scope: SkillScope, name: str, rel_path: str) -> str:
        skill = self._require_bundle(scope, name)
        target = skill.resolve_bundle_path(rel_path)
        if not target.is_file():
            raise FileNotFoundError(f"Bundle file not found: {rel_path}")
        return target.read_text(encoding="utf-8")

    def write_bundle_file(self, scope: SkillScope, name: str, rel_path: str, content: str) -> None:
        skill = self._require_bundle(scope, name)
        target = skill.resolve_bundle_path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._notify_skills_changed()

    def rename_bundle_file(
        self, scope: SkillScope, name: str, old_rel_path: str, new_rel_path: str
    ) -> None:
        if old_rel_path == SKILL_ENTRY_FILE or new_rel_path == SKILL_ENTRY_FILE:
            raise ValueError(f"Cannot rename to/from {SKILL_ENTRY_FILE}")
        if old_rel_path == new_rel_path:
            return
        skill = self._require_bundle(scope, name)
        source = skill.resolve_bundle_path(old_rel_path)
        target = skill.resolve_bundle_path(new_rel_path)
        if not source.exists():
            raise FileNotFoundError(f"Bundle file not found: {old_rel_path}")
        if target.exists():
            raise FileExistsError(f"Destination already exists: {new_rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        self._notify_skills_changed()

    def delete_bundle_file(self, scope: SkillScope, name: str, rel_path: str) -> None:
        if rel_path == SKILL_ENTRY_FILE:
            raise ValueError(f"Cannot delete {SKILL_ENTRY_FILE}; delete the whole skill instead")
        skill = self._require_bundle(scope, name)
        target = skill.resolve_bundle_path(rel_path)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        else:
            raise FileNotFoundError(f"Bundle file not found: {rel_path}")
        self._notify_skills_changed()


    def preview_github_import(self, url: str) -> Dict:
        """Fetch and validate a skill from GitHub, returning a preview dict.

        Does not install the skill; staged temp dir is cleaned up before returning.
        """
        staged = stage_skill_from_github(url)
        try:
            return {
                "name": staged.name,
                "description": staged.description,
                "allowed_tools": staged.allowed_tools,
                "body": staged.body,
                "files": staged.files,
                "source_url": staged.source_url,
                "canonical_url": staged.canonical_url,
                "exists_in_user_scope": self._locate_skill_path("user", staged.name) is not None,
                "exists_in_project_scope": self._locate_skill_path("project", staged.name) is not None,
            }
        finally:
            shutil.rmtree(staged.tmp_root, ignore_errors=True)

    def import_from_github(
        self,
        url: str,
        scope: SkillScope,
        name_override: Optional[str] = None,
        overwrite: bool = False,
        tracks_upstream: bool = False,
    ) -> Skill:
        """Fetch, validate, and install a skill from GitHub into the given scope.

        When ``tracks_upstream=True``, stamps the skill with a `tracks_upstream`
        frontmatter flag so a later sync action can re-fetch from the same
        URL. The initial install doesn't record a `tracking_ref` because
        the staging API doesn't surface the resolved commit SHA; the next
        sync probes the commits API and stamps it.
        """
        staged = stage_skill_from_github(url)
        try:
            name = name_override.strip() if name_override else staged.name
            _validate_name(name)

            scope_dir = self.scope_dir(scope)
            scope_dir.mkdir(parents=True, exist_ok=True)
            target_dir = scope_dir / name
            if target_dir.exists():
                if not overwrite:
                    raise FileExistsError(
                        f"Skill '{name}' already exists in {scope} scope"
                    )
                shutil.rmtree(target_dir)

            shutil.copytree(staged.skill_root, target_dir)

            # Rewrite SKILL.md to (a) honor the user's name override and (b) stamp the
            # canonical GitHub URL into `source:` so we can trace provenance later.
            md_content = serialize_skill_md(
                name,
                staged.description,
                staged.allowed_tools,
                staged.body,
                source=staged.canonical_url,
                tracks_upstream=tracks_upstream,
            )
            (target_dir / SKILL_ENTRY_FILE).write_text(md_content, encoding="utf-8")

            skill = Skill.from_path(target_dir, scope)
            self._notify_skills_changed()
            return skill
        finally:
            shutil.rmtree(staged.tmp_root, ignore_errors=True)

    def sync_tracking_skill(self, scope: SkillScope, name: str) -> dict:
        """Re-fetch a tracking skill from its recorded GitHub source.

        Returns a status dict ``{updated: bool, ref: str|None}``. Raises
        ``FileNotFoundError`` if the skill doesn't exist, ``ValueError`` if
        the skill isn't tracking-eligible (not opted in, no source URL, or
        managed). Network/parse failures bubble up so the HTTP layer can
        surface them as errors; the existing bundle on disk is left intact
        on any error path (the rmtree happens only after staging succeeds).
        """
        skill = self.get_skill(scope, name)
        if skill is None:
            raise FileNotFoundError(f"Skill '{name}' not found in {scope} scope")
        if skill.managed:
            raise ValueError(
                f"Skill '{name}' is managed by the org manifest; sync is "
                "handled by the reconciler, not the track-upstream button."
            )
        if not skill.tracks_upstream:
            raise ValueError(
                f"Skill '{name}' is not tracking upstream; enable tracking "
                "before syncing."
            )
        if not skill.source:
            raise ValueError(
                f"Skill '{name}' has no recorded source URL; cannot sync."
            )

        # SHA probe first. If the commits API returns a SHA equal to the
        # last-synced ref, skip the tarball fetch entirely — saves bandwidth
        # and avoids an unnecessary rmtree/copytree of an unchanged bundle.
        # If the probe fails (None), surface that as an error rather than
        # silently re-downloading: the user clicked the button expecting a
        # fresh check, and a probe-then-fetch dance would mask real outages.
        ref_info = parse_github_url(skill.source)
        desired_sha = resolve_desired_sha(ref_info)
        if desired_sha is None:
            raise RuntimeError(
                "Could not probe GitHub for the latest commit; the existing "
                "skill is unchanged. Try again later."
            )
        if skill.tracking_ref == desired_sha:
            return {"updated": False, "ref": desired_sha}

        staged = stage_skill_from_github(skill.source)
        try:
            # Stage succeeded; replacing the bundle is the destructive step.
            # We preserve the on-disk name (the user may have renamed) and
            # write the tracking pair back so frontmatter stays consistent.
            shutil.rmtree(skill.root_path)
            shutil.copytree(staged.skill_root, skill.root_path)
            md_content = serialize_skill_md(
                skill.name,
                staged.description,
                staged.allowed_tools,
                staged.body,
                source=staged.canonical_url,
                tracks_upstream=True,
                tracking_ref=desired_sha,
            )
            skill.skill_md_path().write_text(md_content, encoding="utf-8")
        finally:
            shutil.rmtree(staged.tmp_root, ignore_errors=True)

        self._notify_skills_changed()
        return {"updated": True, "ref": desired_sha}

    def list_tracking_skills(self) -> List[Skill]:
        """Return only installed skills with `tracks_upstream` set."""
        return [s for s in self.list_skills() if s.tracks_upstream]

    def install_managed_from_github(
        self,
        url: str,
        scope: SkillScope,
        managed_source: str,
        managed_ref: str,
        name_override: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Skill:
        """Install a skill from GitHub as a managed bundle.

        Differs from `import_from_github`:
        - Stamps `managed_source` and `managed_ref` frontmatter keys alongside `source`.
        - Always overwrites existing managed bundles, but refuses to overwrite a
          user-authored bundle of the same name (re-reads frontmatter to check).
        - Accepts an explicit `token` (the deployment's managed-skills token)
          instead of the caller's personal GITHUB_TOKEN / gh-CLI chain.
        """
        staged = stage_skill_from_github(url, token=token)
        try:
            name = name_override.strip() if name_override else staged.name
            _validate_name(name)

            scope_dir = self.scope_dir(scope)
            scope_dir.mkdir(parents=True, exist_ok=True)
            target_dir = scope_dir / name
            if target_dir.exists():
                existing_md = target_dir / SKILL_ENTRY_FILE
                if existing_md.exists():
                    existing = Skill.from_path(target_dir, scope)
                    if not existing.managed:
                        raise FileExistsError(
                            f"Skill '{name}' already exists in {scope} scope "
                            "as a user-authored bundle; refusing to overwrite"
                        )
                shutil.rmtree(target_dir)

            shutil.copytree(staged.skill_root, target_dir)

            md_content = serialize_skill_md(
                name,
                staged.description,
                staged.allowed_tools,
                staged.body,
                source=staged.canonical_url,
                managed_source=managed_source,
                managed_ref=managed_ref,
            )
            (target_dir / SKILL_ENTRY_FILE).write_text(md_content, encoding="utf-8")

            skill = Skill.from_path(target_dir, scope)
            self._notify_skills_changed()
            return skill
        finally:
            shutil.rmtree(staged.tmp_root, ignore_errors=True)

    def list_managed_skills(self) -> List[Skill]:
        """Return only the installed skills that carry a `managed_source`."""
        return [s for s in self.list_skills() if s.managed]


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not SKILL_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid skill name '{name}': {SKILL_NAME_REQUIREMENT}")
