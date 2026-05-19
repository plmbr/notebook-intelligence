# Claude Skills

NBI exposes a top-level **Skills** tab in the settings panel for viewing, creating, editing, and deleting the skills that Claude can invoke. The tab is visible in any mode; when [Claude mode](../README.md#claude-mode) is off, a hint banner notes that skills only take effect inside Claude sessions.

Skills are Claude Agent SDK artifacts stored on disk:

- **User skills**: `~/.claude/skills/`
- **Project skills**: `<project>/.claude/skills/`

Each skill lives in a directory named after the skill, containing a `SKILL.md` entry file (with YAML frontmatter for `name`, `description`, and `allowed-tools`) plus any helper files the skill references.

## The Skills tab

From the tab you can:

- **Add** a new skill in either scope, editing `SKILL.md` and helper files inline.
- **Rename** a skill — NBI updates both the bundle directory and the frontmatter `name`.
- **Duplicate** a skill into the same or opposite scope under a new name.
- **Delete** a skill, with an undo toast that restores the full bundle if clicked within eight seconds.
- Open or delete additional files in the bundle (`SKILL.md` itself is protected from deletion).

When a skill is saved, added, or removed — through the UI or directly on disk — NBI transparently reloads the Claude SDK session (preserving conversation history via session resume), and a **"Skills reloaded"** banner briefly appears in the chat sidebar.

## Importing from GitHub

Click **Import from GitHub** in the Skills tab to install a skill from a public repository.

Paste either:

- A repository URL: `https://github.com/<owner>/<repo>` — imports the repo root if it contains `SKILL.md`.
- A deep link: `https://github.com/<owner>/<repo>/tree/<ref>/<subpath>` — imports the directory at `<subpath>`.

Pick the target scope (user or project) and NBI fetches, validates, and installs the bundle. The canonical source URL is recorded in the skill's frontmatter as `source:` so you can trace where each imported skill came from.

GitHub auth for imports uses, in order: `GITHUB_TOKEN` → `GH_TOKEN` → `gh` CLI auth. Public-repo imports work without auth.

## Tracking upstream for user-imported skills

The Import-from-GitHub dialog has a **Track upstream** checkbox. When you tick it, the installed skill is stamped with a `tracks_upstream: true` frontmatter flag and the Skills panel shows a per-skill **Sync** button (↻) and a panel-level **Sync tracking skills** button.

Tracking is opt-in per skill and entirely manual. Clicking Sync probes GitHub for the latest commit at the recorded `source` URL, and:

- If the commit SHA matches the last recorded `tracking_ref`, the bundle is left alone (no tarball fetch, no rewrite).
- Otherwise NBI fetches the new bundle, replaces the bundle directory on disk, and stamps the new `tracking_ref`.

The bundle on disk is **never deleted** by a sync action, even when:

- The GitHub commits-API probe fails (network outage, rate limit). Sync raises a visible error and the existing bundle stays in place.
- The tarball fetch fails after a successful probe. The rmtree only happens after staging succeeds, so a mid-fetch failure leaves the previous version intact.
- The upstream repo or subpath disappears entirely. Sync errors; the bundle stays.

A tracking skill is the user's. You can still edit its `SKILL.md`, rename it, delete it. The next Sync overwrites local edits the same way `git pull` would.

Tracking is mutually exclusive with the org-managed flag: a skill that the reconciler installed via the org manifest cannot also be set to track upstream from the user-skill side. To migrate, remove it from the manifest first.

To toggle tracking on a skill you already imported (without the checkbox), open the skill in the editor. A **Track upstream** toggle appears for any non-managed skill with a recorded source URL. Toggling off removes the `tracks_upstream` and `tracking_ref` frontmatter and the Sync button disappears; the bundle becomes an ordinary user-authored skill.

The admin policy `allow_github_skill_import = False` blocks sync too: the same network egress is gated by the same flag, so an admin who disables imports also disables sync.

## Managed skills via an org manifest

For organization-wide deployments (e.g., Kubeflow notebooks), NBI can install and keep a curated set of Claude skills in sync from a YAML or JSON manifest. Skills installed this way are marked **Managed** in the UI — they are read-only (edit, rename, and delete are disabled) and refreshed on a schedule.

### Configuration

Configure via environment variables (also available as traitlets on `NotebookIntelligence`):

| Variable                       | Description                                                                                                                                                                             |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NBI_SKILLS_MANIFEST`          | URL (`https://...`) or filesystem path to the manifest, or a comma-separated list of either. Whitespace around each entry is stripped. Empty or unset disables the feature.             |
| `NBI_SKILLS_MANIFEST_INTERVAL` | Seconds between reconciles. Default `86400` (24 hours). Reconciliation also runs once at startup.                                                                                       |
| `NBI_MANAGED_SKILLS_TOKEN`     | Optional bearer token used for **all** managed-skills GitHub operations (see below).                                                                                                    |
| `NBI_SKILL_MAX_ARCHIVE_MB`     | Per-archive on-wire size cap (megabytes) for skill bundles fetched from GitHub. Default `100`. Applies to both user imports and managed-skills tarballs. Set to `0` to disable the cap. |

When set, `NBI_MANAGED_SKILLS_TOKEN` scopes to fetching the manifest, probing commits, and downloading skill tarballs. User-initiated imports (the Import-from-GitHub dialog, `POST /skills/import`) do **not** see this token and continue to use `GITHUB_TOKEN` → `GH_TOKEN` → `gh` CLI auth. When `NBI_MANAGED_SKILLS_TOKEN` is unset, managed operations fall back to that same chain. When it is set and a managed operation fails with an auth error, it fails loudly (no retry with the fallback chain) so misconfigured or expired tokens stay visible to the admin. The minimum required GitHub scope is `contents:read`.

### Manifest schema

```yaml
skills:
  - url: https://github.com/org/repo/tree/main/skills/data-eda
    name: data-eda # optional: override the installed skill name
    scope: user # optional: "user" (default) or "project"
  - url: https://github.com/org/repo/tree/main/skills/ml-recipes
```

JSON is also accepted (the parser is `yaml.safe_load`).

### Reconciler behavior

- The reconciler probes GitHub's commits API for each entry's `subpath` and `ref`, and skips fetching the tarball when the installed `managed_ref` matches the latest SHA. Full-SHA URLs skip the probe.
- Managed skills present in the install but missing from every manifest are **removed**.
- User-authored skills are never touched. If a user-authored skill has the same name as a manifest entry, the reconciler leaves it alone and reports a per-entry error.
- A manual **Sync managed skills** button appears in the Skills panel when any managed skill is installed.
- A `POST /notebook-intelligence/skills/reconcile` endpoint is available for scripted triggers.
- If a manifest cannot be loaded (network failure, bad YAML, missing `skills:` list), the reconciler logs the error and leaves managed skills in place rather than mass-deleting on a transient failure. With multiple manifests configured, removal of stale managed skills is also skipped for the cycle so the skills owned by an unreachable manifest don't get orphaned.

### Multiple manifests

`NBI_SKILLS_MANIFEST` accepts a comma-separated list, e.g. `https://manifests.acme/org.yaml,https://manifests.acme/team.yaml,/srv/local.yaml`. Manifests are unioned, with two layers of dedupe:

- **Same `url:` listed by two manifests**: the earlier source wins, a WARN names both manifests, reconciliation continues.
- **Two different URLs resolve to the same installed skill name** (either via explicit `name:` overrides or by URL-subpath collision): the second entry is dropped with a per-entry error, leaving the first install intact.

The order of sources in the list determines first-wins precedence. A URL containing a literal comma is not supported.

> **Trust-boundary note for `NBI_MANAGED_SKILLS_TOKEN`.** When set, the token is sent as a `Bearer` `Authorization` header to **every** URL in the manifest list, including non-GitHub hosts. The no-redirect handler blocks server-side redirect-driven leaks, but it cannot stop a typo'd entry from receiving the token. If you mix trust domains (e.g. an org-internal manifest URL plus an external one), either point every source at the same trust boundary or split the deployment into separate spawn profiles with their own tokens.

### Multi-tenant scoping

Different JupyterHub profiles or spawner configurations can point at different manifests by setting `NBI_SKILLS_MANIFEST` per profile. Within a single user's install, skills are namespaced by name — so two profiles that both install a skill called `data-eda` will collide if a user moves between them. Use distinct skill names across teams to avoid this.

### Disabling user-initiated GitHub imports

Set `allow_github_skill_import = False` on `NotebookIntelligence` (or `NBI_ALLOW_GITHUB_SKILL_IMPORT=false` per pod) to hide the **Import from GitHub** button and reject `POST /skills/import` and `/skills/import/preview` with HTTP 403. The managed-skills reconciler keeps running, so admin-curated skills delivered via `NBI_SKILLS_MANIFEST` continue to install. The env-var override accepts `true`/`false`/`1`/`0`/`yes`/`no`/`on`/`off` (case-insensitive); unrecognized values raise at startup so a typo can't silently flip the policy.

For network-layer reinforcement, also gate egress to `github.com` and `api.github.com` and rely on `NBI_SKILLS_MANIFEST` with a private internal manifest URL.

### Disabling the entire Skills tab

For a stricter posture, set `skills_management_policy = "force-off"` (or `NBI_SKILLS_MANAGEMENT_POLICY=force-off`). This hides the Skills tab, returns 403 from every `/notebook-intelligence/skills/*` route, and suppresses the managed-skills reconciler entirely (no manifest fetch, no scheduled reconcile). Existing skills on disk are not touched, but new manifest pulls are blocked. See the [admin guide](admin-guide.md#disabling-the-skills-tab) for the full contract and blast radius.
