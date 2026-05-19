"""Background reconciliation of managed Claude skills against one or more
manifests.

Reads the manifests pointed at by `NBI_SKILLS_MANIFEST` (comma-separated),
installs/updates the skills they list from GitHub, and removes managed skills
that no longer appear in any manifest. User-authored skills are never touched.

See `skill_manifest.py` for the manifest schema and the multi-manifest merge
rules.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, cast

from notebook_intelligence.skill_github_import import (
    parse_github_url,
    resolve_desired_sha,
)
from notebook_intelligence.skill_manager import SkillManager
from notebook_intelligence.skill_manifest import (
    ManifestEntry,
    load_manifests,
)
from notebook_intelligence.skillset import Skill, SkillScope

log = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    errors: List[str] = field(default_factory=list)

    def mutated(self) -> bool:
        return self.added or self.updated or self.removed

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "unchanged": self.unchanged,
            "errors": list(self.errors),
        }


class SkillReconciler:
    """Reconciles installed managed skills against one or more manifests."""

    def __init__(
        self,
        skill_manager: SkillManager,
        manifest_sources: List[str],
        interval_seconds: int,
        managed_token: Optional[str] = None,
    ):
        self._skill_manager = skill_manager
        # Defensive copy: callers pass in the resolved list at construct time
        # and we don't want a later mutation to silently change the set of
        # manifests reconciled.
        self._manifest_sources = list(manifest_sources)
        self._interval_seconds = max(int(interval_seconds), 1)
        # Used for manifest fetch, commits-API probe, and tarball download — the
        # whole managed pathway. User-initiated imports do not see this token.
        self._managed_token = managed_token
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        # Guards `_thread` / `_stop` mutations across `start()` / `stop()`.
        # The admin kill-switch endpoint (`SkillsReconcilerStopHandler`) is
        # reachable from any authenticated request and a double-click during
        # an incident must not orphan a daemon thread or race start()'s
        # `_stop.clear()` against stop()'s `_stop.set()`.
        self._lifecycle_lock = threading.Lock()

    def reconcile(self) -> ReconcileResult:
        """One pass: load manifests, apply installs/updates/removes. Synchronous."""
        result = ReconcileResult()
        merged = load_manifests(
            self._manifest_sources, token=self._managed_token
        )

        # Surface per-source diagnostics first so they appear in
        # `ReconcileResult.errors` / log output before any per-entry errors.
        for warning in merged.warnings:
            log.warning(warning)
        for err in merged.errors:
            log.error(err)
            result.errors.append(err)

        # If we configured N manifests but fewer than N loaded, some source is
        # unreachable. Skip stale removal so a transient outage doesn't orphan
        # the skills owned by the missing manifest. Per-entry installs still
        # run against whatever did load.
        all_sources_loaded = (
            len(merged.loaded_sources) == len(self._manifest_sources)
        )

        # Snapshot managed skills once per cycle. Both the per-entry apply and
        # the stale-removal pass read from this dict, avoiding an O(N*M) disk
        # re-scan for every manifest entry.
        managed_by_url: Dict[str, Skill] = {
            s.managed_source: s
            for s in self._skill_manager.list_managed_skills()
            if s.managed_source
        }
        manifest_urls = {entry.url for entry in merged.manifest.entries}

        for entry in merged.manifest.entries:
            try:
                self._apply_entry(entry, managed_by_url, result)
            except Exception as e:  # noqa: BLE001 — per-entry isolation
                msg = f"{entry.url}: {e}"
                log.exception("Failed to reconcile skill %s", entry.url)
                result.errors.append(msg)

        if all_sources_loaded:
            self._remove_stale(manifest_urls, managed_by_url, result)
        elif managed_by_url:
            log.info(
                "Skipping stale-managed-skill removal: %d/%d manifest sources "
                "failed to load this cycle; existing managed skills are "
                "preserved until every source reloads successfully.",
                len(self._manifest_sources) - len(merged.loaded_sources),
                len(self._manifest_sources),
            )

        # Intermediate install/delete calls each fire the skill_manager's listeners
        # already; the downstream Claude client update is debounced, so per-entry
        # notifications coalesce into a single reconnect.

        return result

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None:
                return
            self._stop.clear()
            self._thread = threading.Thread(
                name="Skill Reconciler",
                target=self._run_loop,
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        # Signal first, then join outside the lock so an admin who hits the
        # kill switch a second time during a hung fetch doesn't block on a
        # held lifecycle lock — the second call sees `_thread is None` and
        # is a fast no-op.
        with self._lifecycle_lock:
            thread = self._thread
            self._thread = None
            self._stop.set()
        if thread is not None:
            thread.join(timeout=timeout)

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _policy_force_off() -> bool:
        """Re-read NBI_SKILLS_MANAGEMENT_POLICY at runtime so the reconciler
        can honor an env-var flip without a server restart. Used as the
        per-cycle kill switch so admins who can update pod env in place have
        a working stop signal beyond the explicit HTTP endpoint."""
        return os.environ.get("NBI_SKILLS_MANAGEMENT_POLICY", "").strip().lower() == "force-off"

    def _run_loop(self) -> None:
        # First pass runs immediately, then we sleep between reconciles.
        while not self._stop.is_set():
            if self._policy_force_off():
                log.info(
                    "NBI_SKILLS_MANAGEMENT_POLICY is force-off; stopping the "
                    "managed-skills reconciler. Existing skills on disk are "
                    "not touched."
                )
                self._stop.set()
                return
            try:
                self.reconcile()
            except Exception:  # noqa: BLE001 — thread must survive any error
                log.exception("Reconciler pass raised; continuing")
            if self._stop.wait(self._interval_seconds):
                return

    def _apply_entry(
        self,
        entry: ManifestEntry,
        managed_by_url: Dict[str, Skill],
        result: ReconcileResult,
    ) -> None:
        ref_info = parse_github_url(entry.url)
        existing = managed_by_url.get(entry.url)
        desired_sha = self._resolve_desired_sha(ref_info)

        # Already installed and the SHA still matches — nothing to do.
        if existing is not None and desired_sha and existing.managed_ref == desired_sha:
            result.unchanged += 1
            return

        # Probe failed (None) and we already have this skill installed — leave it
        # alone rather than re-downloading the tarball every cycle on transient
        # commits-API errors. A genuine upstream update will produce a concrete
        # SHA on a later cycle.
        if existing is not None and desired_sha is None:
            result.unchanged += 1
            return

        self._skill_manager.install_managed_from_github(
            url=entry.url,
            scope=cast(SkillScope, entry.scope),
            managed_source=entry.url,
            managed_ref=desired_sha or "",
            name_override=entry.name,
            token=self._managed_token,
        )
        if existing is not None:
            result.updated += 1
        else:
            result.added += 1

    def _resolve_desired_sha(self, ref_info) -> Optional[str]:
        return resolve_desired_sha(ref_info, token=self._managed_token)

    def _remove_stale(
        self,
        manifest_urls: set,
        managed_by_url: Dict[str, Skill],
        result: ReconcileResult,
    ) -> None:
        for url, skill in managed_by_url.items():
            if url in manifest_urls:
                continue
            try:
                self._skill_manager.delete_skill(skill.scope, skill.name)
                result.removed += 1
            except Exception as e:  # noqa: BLE001
                msg = f"Could not remove stale managed skill {skill.name}: {e}"
                log.exception(msg)
                result.errors.append(msg)
