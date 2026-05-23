# Changelog

All notable changes to Notebook Intelligence are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) starting with 4.0.0.

For each release we list user-facing changes grouped as **Added**, **Changed**, **Fixed**, and **Removed**. Commits are squashed into the change that motivated them; the full git log remains the source of truth for low-level history.

<!-- <START NEW CHANGELOG ENTRY> -->

## [Unreleased]

## [5.0.0] - 2026-05-22

5.0.0 is a major release built on top of 4.8.0, gathering a large surface of new admin policies, accessibility work across the chat sidebar / popovers / settings tabs, several security hardening passes, and three new agent-aware UI surfaces. Most existing configuration continues to work; the version bump reflects the breadth of new admin-policy / env-var surface that operators should review, plus the dependency swap from `fastmcp` to the official `mcp` SDK.

### Migration note

5.0.0 ships no traitlet, env-var, REST route, or NBI-owned on-disk format renames or removals. Four items operators should review before upgrading:

- **`fastmcp` is no longer a dependency** (#324). NBI now uses the official `mcp` SDK via a thin internal shim. If your image pinned `fastmcp` because prior docs recommended it, drop that pin. If you have downstream Python code that imported `fastmcp` transitively via NBI, declare `fastmcp` as a direct dependency in your own image.
- **Shell tool and Claude UI-bridge tool paths are now sandboxed to `jupyter_root`** (#290, #323). An agent-supplied absolute path or `..` traversal that previously resolved outside the workspace is now rejected. Workflows that relied on the agent reaching outside the workspace via these tools need to move that data into the workspace.
- **Session listing no longer reads `~/.claude/projects/<cwd>/history.jsonl`** (#310). No action required: the unified inventory walks `~/.claude/projects/` directly, and a stale or missing `history.jsonl` no longer hides resumable sessions.
- **Workspace file attach in Claude mode ships an `@`-mention pointer instead of inlined file content** (#327). Behavior change visible to end users (images, large files, and notebooks now work where they didn't); no admin action required, but Claude's Read tool counts toward tool-use quotas that the prior content-injection path did not.
- **Copilot WebSocket upgrades require Jupyter session authentication and pass an origin check** (#301). Cross-origin and unauthenticated upgrade attempts that previously succeeded against `WebsocketCopilotHandler` now return 403. If you have a custom client outside the JupyterLab page hitting this endpoint, it needs to pipe through Jupyter's auth (token or cookie) and either set its `Origin` to the lab's origin or have it added to `c.ServerApp.allow_origin`.

### Added

#### Settings: three new top-level tabs and policy gates

- **Skills as a top-level Settings tab** (#224). Promoted from a Claude-mode sub-tab; visible in any mode, with a hint banner when Claude mode is off. New admin policy `skills_management_policy` (env `NBI_SKILLS_MANAGEMENT_POLICY`); `force-off` hides the tab, returns HTTP 403 from every `/notebook-intelligence/skills/*` route, and suppresses the managed-skills reconciler.
- **Claude MCP Servers tab** (#225) for managing the user, project, and local-scope MCP entries Claude Code reads from `~/.claude.json` and `<project>/.mcp.json`. Independent of the existing NBI MCP tab; the two never appear at the same time. New admin policy `claude_mcp_management_policy` (env `NBI_CLAUDE_MCP_MANAGEMENT_POLICY`).
- **Claude Plugins tab** (#226) wrapping `claude plugin` for install / uninstall / enable / disable / marketplace add. New admin policies `claude_plugins_management_policy` (env `NBI_CLAUDE_PLUGINS_MANAGEMENT_POLICY`) and `allow_github_plugin_import` (env `NBI_ALLOW_GITHUB_PLUGIN_IMPORT`), the latter mirroring `allow_github_skill_import` for marketplace sources.
- **Plugin marketplace picker** (#284). Browse the configured marketplaces and install plugins inline; the picker shows source repo, version, and description for each entry.
- **Plugin marketplace details + Update button** (#303). The Plugins tab now displays each installed plugin's description, author, version, and source, and surfaces a per-plugin **Update** button when a newer version is available upstream.
- **Per-workspace MCP server disable** for Claude mode (#286). Toggle individual MCP entries on/off without removing them, scoped to the current Jupyter workspace.
- **JSON-paste path in the Add MCP server dialog** (#285). Paste a Claude / Cursor / VS Code MCP config blob; NBI parses, validates, and pre-fills the form.
- **GitHub auth for plugin marketplace add**. Marketplace sources that resolve as GitHub URLs or `owner/repo` shorthand reuse Skills' `GITHUB_TOKEN` / `GH_TOKEN` / `gh auth token` precedence; tokens are injected into the `claude plugin marketplace add` subprocess via env, never argv.

#### Launchers

- **Launcher tiles for opencode, Pi, and GitHub Copilot CLI** (#268), with follow-ons for **OpenAI Codex** and brand icons for Codex and opencode (#333). Each tile appears when the corresponding binary is on `PATH` and opens a Jupyter terminal at the file-browser's current directory. CLI path overrides: `NBI_OPENCODE_CLI_PATH`, `NBI_PI_CLI_PATH`, `NBI_GITHUB_COPILOT_CLI_PATH`, `NBI_CODEX_CLI_PATH`. Capabilities response gains matching `*_cli_available` booleans.
- **Coding-agent launcher tiles can be hidden by admin policy** (#288). New traitlet `disabled_coding_agent_launchers` (list of `claude-code` / `opencode` / `pi` / `github-copilot-cli` / `codex`) with an optional `allow_enabling_coding_agent_launchers_with_env` + `NBI_ENABLED_CODING_AGENT_LAUNCHERS` per-pod re-enable mechanism. The Coding Agent section header now uses the sparkles icon instead of the Claude orange so the section is correctly framed when other tiles are enabled (#325).
- **Claude Code launcher tile is no longer gated by Claude chat mode** (#239); it appears whenever the `claude` CLI is on `PATH`.
- **Choose a start directory from the launcher tile** (#332). Clicking any coding-agent tile (or "New Session" on the Claude resume dialog) opens a directory picker so the terminal starts where the user wants.

#### Chat sidebar and agentic UX

- **Real progress feedback during long Claude tasks** (#254). Elapsed-time counter, heartbeat-driven pulse with a "may be slow" copy flip after 30 seconds, and inline tool-call narration.
- **"New chat session" button** in the chat sidebar header restarts the Claude SDK client, mirroring `/clear` (#246).
- **Terminal drag-drop file attach** with `@`-mention or shell-escaped raw modes and a per-terminal toolbar toggle (#256). New admin policy `NBI_TERMINAL_DRAG_DROP_POLICY`; tunables `NBI_UPLOAD_MAX_MB` (default `50`) and `NBI_UPLOAD_RETENTION_HOURS` (default `24`) govern the shared upload-staging endpoint used by both terminal drops and chat-sidebar attachments.
- **Workspace files attach as `@`-mention in Claude mode** (#327). Instead of reading file contents client-side and injecting them as a fenced code block, the backend emits an `@<workspace-relative-path>` pointer and Claude's Read tool decides what to load. Unblocks images, large files, and notebooks (cell-aware reads) that the content-injection path couldn't handle. Notebook cell-pointer prose and text-selection line ranges are preserved so deictic references ("explain this cell", "why is this broken") still have a referent.
- **Hover preview for image context thumbnails** (#267).
- **Reload open document tabs when their files change on disk** (#330, relocated in #339). Polls every open `DocumentWidget` and reverts via `context.revert()` when disk is newer than the in-memory model, skipping when the tab has unsaved local edits. New user setting `refresh_open_files_on_disk_change` (default `true`); flip in the **NBI Settings dialog → External changes**. Closes the agentic-experience gap where Claude edits a file but the open tab keeps showing the pre-edit version. Admins can pin via the matching `NBI_REFRESH_OPEN_FILES_ON_DISK_CHANGE_POLICY` env var or `refresh_open_files_on_disk_change_policy` traitlet.
- **First-run tour of the chat sidebar** (#304). Highlights the gear, file-attach button, chat-mode dropdown, and (when available) the Claude session history icon. Replays from the command palette via "Show NBI tour"; capability-aware so steps for unavailable CLIs are skipped.
- **Steered the Claude system prompt away from over-eager notebook creation** (#336). The agent now defaults to answering questions in chat instead of creating a new notebook to hold the answer when the user attaches a file and asks a question about it.

#### Copilot models

- **Dynamic GitHub Copilot model discovery** (#269). NBI queries `https://api.githubcopilot.com/models` on each Copilot token refresh and rebuilds the chat-model dropdown from the live response, falling back to a hardcoded list on transient failure.
- **Newer GitHub Copilot chat models** added to the fallback list (#255).

#### Skills and workspace config

- **Multi-manifest support** in `NBI_SKILLS_MANIFEST` / `skills_manifest` (#321). Comma-separated list of URLs and/or filesystem paths; manifests are unioned with first-wins URL dedupe and per-entry name-collision surfacing. See [`docs/skills.md`](docs/skills.md#managed-skills-via-an-org-manifest).
- **Tracks-upstream flag for user-imported GitHub skills** (#322). The Import-from-GitHub dialog adds a **Track upstream** checkbox; tracked skills get a per-skill Sync button and a panel-level **Sync tracking skills** button. Mutually exclusive with the managed-skills reconciler: a skill the reconciler installs can't also be marked tracking.
- **HTTP kill switch for the managed-skills reconciler** (#291). `POST /notebook-intelligence/skills/reconciler/stop` is authenticated, idempotent, and intentionally has no `/start` companion (a kill switch a script can flip back on isn't a kill switch). The reconciler also re-reads `NBI_SKILLS_MANAGEMENT_POLICY` at the start of each cycle and self-stops when it reads `force-off`.
- **Skill GitHub archive cap raised to 100 MB**, configurable (#257). New traitlet `skill_max_archive_mb` (env `NBI_SKILL_MAX_ARCHIVE_MB`); `0` disables the cap.
- **`additional_skipped_workspace_directories` accepted in NBI `config.json`** (#241), layered additively on top of the existing traitlet, env, and env-prefix layers so a per-user override extends rather than replaces the org-wide list.

### Changed

#### Accessibility (chat sidebar, popovers, settings)

A multi-PR accessibility pass landed across most NBI surfaces. Together these make NBI navigable end-to-end with the keyboard and screen-reader, audited under JupyterLab's light, dark, and high-contrast themes:

- **Chat-sidebar header icons** are real keyboard-reachable buttons (#205, #305) with distinct titles / `aria-label`s and a button reset to avoid double-borders.
- **Settings tabs** are an ARIA tablist with arrow-key navigation (#206).
- **Workspace, tools, and slash popovers** are keyboard-first (#306), with focus restoration to the trigger element on close.
- **Settings checkboxes** have the WAI-ARIA `checkbox` role and respond to Space activation (#309).
- **Ask-User-Question form** uses `radio` for single-select choices, stable per-form `useId`-driven labels, and real form semantics (#307).
- **Claude MCP form** wires every input to a `<label>` (#308).
- **"Open notebook" link in chat replies** is a real button with the notebook path in its accessible name (#311).
- **Skills panel icons** render as real SVGs with focus-reveal styling; the nested-button wrapper is gone (#312).
- **Send button** swaps its color to the warn-token and updates its `aria-label` while a request is in flight (#313).
- **Inline-completion popover** uses JupyterLab theme tokens instead of a fixed pastel background so it reads correctly under dark/high-contrast themes (#314).
- **Upload-in-progress chip** announces via `role=status`, `aria-live=polite`, `aria-busy=true`, plus an animated ellipsis with `prefers-reduced-motion` honored (#315).
- **Drop-zone chip** uses theme-aware foreground color so the text is legible against the brand-tinted background (#316).
- **Generating-state rotating border** pauses under `prefers-reduced-motion` (#317).
- **Streaming chat replies** announce through an `aria-live=polite` region with chunked boundary announcements (#318).
- **Visually-hidden skip-to-message-input link** as the first focusable child of the sidebar (#319). Lets keyboard users jump past long transcripts to the prompt input.
- **Global Ctrl/Cmd+Shift+L shortcut** focuses the NBI chat input from anywhere in the app (#320).

- **Chat-input footer icons reworded** for clarity; the gear button gains a `title` attribute (#271).
- **Cell-tool descriptions** mention zero-based indexing so models pick the right cell (#265).

### Removed

- **`fastmcp` dependency**, replaced with the official `mcp` SDK (#324). NBI's external behavior is unchanged; downstream code that imported `fastmcp` transitively via NBI now needs to depend on it directly.
- **`history.jsonl` as the gate for session listing** (#310). The unified inventory walks the projects directory directly.

### Fixed

- **Websocket writes from worker threads** no longer raise `BufferError` after `/clear` or "new chat" on Python 3.13+ (#270). All emitter writes route through `tornado.IOLoop.call_soon_threadsafe`.
- **WebSocket message-callback handlers** are freed when requests finish, preventing slow accumulation over the lifetime of a session (#294).
- **Claude session listing** unified across the chat-sidebar picker and the launcher tile; both surfaces read the same on-disk transcript inventory and apply the same "show this session?" filter so they no longer disagree (#310). The legacy `history.jsonl` gate is removed.
- **Claude session preview** correctly strips the NBI context preamble when `claude.py` joined it onto the user's actual prompt (#331). Single-turn sessions previously showed a blank title; now they show the prompt.
- **Refresh-on-disk watcher** no longer throws `Invalid area: down` on every poll (post-#330 follow-up). The TS `Area` union lists `'down'`, but `LabShell.widgets()` doesn't implement it.
- **Cell tools** follow the active notebook when the user switches tabs (#253).
- **`is_connected()`** stabilized against the Claude worker-spawn resurrection race (#250).
- **Persisted Claude model** now displays after a JupyterLab restart (#244).
- **`/clear` no longer duplicated** in the `@`-mention autocomplete (#243).
- **`@`-mention picker** refreshes when workspace files change (#251) and closes on Escape from the search input (#266).
- **Notebook-toolbar prompt textarea** focuses when the popover opens (#240); the update button works outside Claude mode (#238).
- **Inline chat** anchors to the cursor line (#191).
- **Disabled send button** styled neutrally instead of as a primary action (#276); Claude tool-result check renders on the right of its label (#277).
- **Plugin Settings row** shows the plugin name even when the CLI returns only `id` (#280).

### Security

- **Shell tool's `working_directory` is sandboxed to `jupyter_root`** (#290). A previously-permitted absolute path or `..` traversal in agent-supplied input is now rejected; the existing path-safety helper handles the canonicalization.
- **Claude UI-bridge tool paths sandboxed to `jupyter_root`** (#323). `open_file_in_jupyter_ui` and `run_command_in_jupyter_terminal` both route through `safe_jupyter_path` so an agent can't reach files outside the workspace via these tools. The Claude Agent SDK subprocess is itself rooted at `jupyter_root` via its `cwd` option.
- **Encrypted GitHub token file enforces mode 0o600** (#293). The file holding the AES-GCM-encrypted Copilot token is created and re-tightened to owner-only read/write on every save, so an out-of-band `chmod` that widens permissions is undone on the next write.
- **Process-env secrets are scrubbed from shell-tool output** (#295). The shell tool no longer leaks `API_KEY` / `TOKEN` / `SECRET`-like env values into the captured stdout/stderr block returned to the model.
- **MCP user config shape validated before persisting** (#299). Malformed entries in the JSON paste / Add-MCP dialog are rejected server-side (unknown keys, type/command/url consistency, etc.); the client surfaces the rejection as a notification rather than writing through.
- **Anchor URIs in chat messages filtered against an XSS allowlist** (#296). `javascript:`, `data:`, `vbscript:`, and tab/NEL/bidi-override codepoint smuggling are blocked at render time.
- **Copilot WebSocket upgrades authenticated and origin-checked** (#301). Cross-origin and unauthenticated upgrade attempts are refused.
- **GitHub Enterprise host detection for marketplace add** (#292), so a `git.acme.example.com` URL routes through the GHE token / API path instead of being misclassified as public GitHub. Hardened against trailing-dot, userinfo, and other URL-shape edge cases.
- **`fastmcp` dropped in favor of the official `mcp` Python SDK** (#324). `fastmcp` pinned `python-dotenv>=1.1.0` which conflicted with `litellm`'s `python-dotenv==1.0.1` pin; the swap unblocks installs on Python 3.14 and picks up CVE fixes via `urllib3>=2.7.0` (CVE-2026-44431 / CVE-2026-44432).
- **Runtime kill switch for the managed-skills reconciler** (#291) provides per-pod incident response without a server restart. See the Skills entry above for the user-facing affordances and the [admin guide](docs/admin-guide.md#disabling-the-skills-tab) for the route and self-stop semantics.

### Internal

- **CVE-driven dependency upgrades** (#197); `react-icons` bumped to `~5.6.0` (#245).
- **Galata-based Playwright UI test suite scaffolded** (#207) and expanded with user-flow specs covering the chat sidebar, notebook toolbar, cell outputs, and the launcher (#272).
- **Docs refresh across README, admin guide, skills, and CHANGELOG** (#287) covering the post-4.8.0 surface that this release expands on.
- **Stop tracking local AI-assistant config files** (`.codex/`, `.claude/scheduled_tasks.lock`) via `.gitignore` so they don't clutter the diff when contributors run the agents inside the repo.
- **Contributor docs** cover the traitlet vs env var vs config-file decision (#242).

<!-- <END NEW CHANGELOG ENTRY> -->

## [4.8.0] - 2026-05-11

### Added

- **`allow_github_skill_import` traitlet** (env `NBI_ALLOW_GITHUB_SKILL_IMPORT`) gating user-initiated skill imports from GitHub independently of the managed-skills reconciler (#222). When `False`, the **Import from GitHub** button hides and `/skills/import` returns HTTP 403.
- **Workspace picker honors `.gitignore`** and gains the `additional_skipped_workspace_directories` traitlet (env `NBI_ADDITIONAL_SKIPPED_WORKSPACE_DIRECTORIES`, layered additively) for extending the built-in skip list (#223). Dot-prefixed files are also skipped by default (#221).
- Workspace file scan in the `@`-mention picker now runs in parallel (#227).

### Changed

- Skill imports from GitHub block and scope HTTP redirects, including refusing HTTPS-to-HTTP downgrades (#203).
- Settings tab content scrolls correctly when its body is taller than the dialog (#228); the tab bar styling is standardized across tabs.

### Fixed

- `NBIConfig.save()` is atomic (#202): symlinks are preserved, file mode is preserved across the swap, and the rename is parent-dir fsynced. Prevents the corrupt-config failure mode where a crash mid-write left an empty `config.json`.
- The NBI notebook toolbar is disabled outside Claude mode where its buttons did not work (#228); a stray new-notebook button was removed.

## [4.7.0] — 2026-05-07

### Added

- **Cell output actions** — right-click a cell output (or hover for the toolbar) for **Explain**, **Ask**, and **Troubleshoot** quick actions that open the chat sidebar with the output already attached as context. Outputs forward as structured MIME bundles and include images for vision-capable models, token-bounded so large outputs don't overflow the context window. Per-user toggles in `config.json` (`enable_explain_error`, `enable_output_followup`, `enable_output_toolbar`, default on); admins can lock them via `NBI_EXPLAIN_ERROR_POLICY` / `NBI_OUTPUT_FOLLOWUP_POLICY` / `NBI_OUTPUT_TOOLBAR_POLICY`.
- **Image attachments in chat** — paste or attach images alongside a prompt; the image goes to the model as input when it's vision-capable.
- **Streaming inline-chat responses** — the inline chat popover now streams tokens as they arrive instead of waiting for the full response.
- **Notebook toolbar generation button** — a sparkle icon on the active notebook's toolbar opens a popover that scopes the generation to that notebook.
- **Claude Code launcher tile** — a Claude Code tile in the JupyterLab launcher opens a session picker (resume a transcript or start a new one in the file browser's active subdirectory). Session IDs are copyable from the picker.
- **Repo-level `AGENTS.md`** — when a project root contains `AGENTS.md`, NBI appends it under the system prompt's "Additional Guidelines" alongside the existing ruleset injection.
- **Claude WebSocket heartbeat** — keeps long-running Claude agent requests alive through upstream proxy / load balancer idle timeouts (e.g. JupyterHub's nginx default of 60s) by sending a status heartbeat every 20s while a request is in flight. Fixes Bedrock-style request failures where processing exceeds the proxy idle window.
- **Extended admin policy coverage** — every Settings panel toggle is now lockable via an env var. New boolean policies: `NBI_CLAUDE_MODE_POLICY`, `NBI_CLAUDE_CONTINUE_CONVERSATION_POLICY`, `NBI_CLAUDE_CODE_TOOLS_POLICY`, `NBI_CLAUDE_JUPYTER_UI_TOOLS_POLICY`, `NBI_CLAUDE_SETTING_SOURCE_USER_POLICY`, `NBI_CLAUDE_SETTING_SOURCE_PROJECT_POLICY`, `NBI_STORE_GITHUB_ACCESS_TOKEN_POLICY`. New value-presence locks: `NBI_CHAT_MODEL_PROVIDER`, `NBI_CHAT_MODEL_ID`, `NBI_INLINE_COMPLETION_MODEL_PROVIDER`, `NBI_INLINE_COMPLETION_MODEL_ID`, `NBI_CLAUDE_CHAT_MODEL`, `NBI_CLAUDE_INLINE_COMPLETION_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`. See [README → Admin policies](README.md#admin-policies).
- `/claude-sessions` HTTP route accepts `?scope=cwd` to filter to sessions whose recorded `cwd` matches the lab's working directory.

### Changed

- Claude agent connection now happens in the background so JupyterLab finishes loading without waiting on the SDK handshake.

### Fixed

- Public-API hygiene in `notebook_intelligence.api`: `raise NotImplemented` → `raise NotImplementedError` (the former raised `TypeError` at the call site), `Toolset(tools=[])` and four other shared-default-argument cases corrected, `Signal.disconnect` tolerates double-disconnect with a debug-level log, registrar methods raise a new `RegistrationError` instead of silently logging.
- Claude headers (model + version) are now sent on inline completion calls, matching the chat path.
- OpenAI-compatible provider drops the unsupported `tool` `strict` flag when targeting vLLM (#108).
- Resolve symlinks when locating Claude session transcripts so `~/.claude/projects/` symlinked off another volume keeps working.
- Claude worker thread no longer crashes on cancellation; the chat loop recovers cleanly.
- "Generating..." row no longer reflows the chat sidebar on narrow widths.
- Skills popup in the chat sidebar dismisses on click-outside or when the input is cleared.
- Spurious "Skills reloaded" notification when launching a Claude session. The watcher now keys off a structural signature of bundle dirs + `SKILL.md` mtimes, ignoring sibling writes (`.DS_Store`, `.git/`, log/cache files) to the parent `~/.claude/skills/` directory.
- Traitlets `DeprecationWarning` ("Traits should be given as instances, not types") at startup is silenced for the `disabled_*` config.

### Internal

- CI runs `pytest tests/` and `jlpm test` on every PR. The `[test]` extra was added to `pyproject.toml`. Both build jobs declare `permissions: { contents: read }` so a compromised step can't push.

<!-- <END NEW CHANGELOG ENTRY> -->

## [4.6.0] — 2026-04-29

### Added

- **Claude Skills management panel** — Settings now exposes a **Skills** tab for managing the bundles Claude can invoke (SKILL.md frontmatter, helper files, allowed tools). Skills resolve from `~/.claude/skills/` (user) and `<project>/.claude/skills/` (project) — the same locations the Claude CLI reads. Inline editor, duplicate / rename / delete with undo, and import-from-GitHub via the public tarball API. For organization deployments, NBI can install a curated set from a YAML manifest pointed at by `NBI_SKILLS_MANIFEST` and keep them in sync; managed skills are read-only in the UI. See [`docs/skills.md`](docs/skills.md) for the full reference.
- Restructured documentation: `README.md` rewritten with a TOC and concept glossary, plus new `SECURITY.md`, `PRIVACY.md`, and operator guides under `docs/` (`admin-guide.md`, `rulesets.md`, `skills.md`, `troubleshooting.md`).

### Fixed

- **Windows Claude mode reliability** — Claude agent thread now uses the Proactor event loop on Windows, fixing subprocess spawn failures and intermittent "Claude agent not connected" races at startup. The Claude SDK retry path also reconnects when the worker thread has died instead of waiting out the full response timeout.
- Anthropic credentials are normalized (whitespace + scheme handling) before being passed to the SDK.
- Skill imports from GitHub reject tarball entries with absolute paths or `../` traversal — a malicious or buggy bundle can no longer write outside its install directory.
- `_send_claude_agent_request` guarded against the disconnect race that left chat handlers waiting on a closed queue.
- WebSocket message handlers are disconnected when the originating request finishes; previously they accumulated for the lifetime of the WebSocket.
- `configChanged` handlers are disconnected when components unmount, fixing a slow leak when the chat sidebar was opened and closed repeatedly.
- Claude session picker list scrolls correctly when the transcript count exceeds the visible area.

<!-- This entry was filled in retroactively after the 4.6.0 tag shipped. -->

## [4.5.0] — 2026-04-09

### Added

- Chat feedback mechanism for AI responses, configurable via the `enable_chat_feedback` traitlet, with a `telemetry` event hook.
- Attach files as context in chat.
- `Shift+Enter` inserts a newline in the chat input.
- Disable LLM providers via the `disabled_providers` traitlet, with optional per-pod re-enable via `NBI_ENABLED_PROVIDERS`.

### Changed

- Inline completion for the OpenAI-compatible provider now uses the Chat Completions API.

### Fixed

- OpenAI-compatible provider now correctly handles `tool` and `tool_choice` parameters.
- File-attach popover styling.
- Newlines in user input are preserved.

## [4.4.0] — 2026-03-13

### Added

- Configurable Claude Code CLI path via the `NBI_CLAUDE_CLI_PATH` environment variable.

### Changed

- Subprocess invocations no longer use `shell=True`.

## [4.3.2] — 2026-03-13

### Fixed

- Refresh-models button in Claude settings; model list pulled from the Anthropic SDK.

## [4.3.1] — 2026-01-12

### Fixed

- Inline-chat autocomplete popover position.

## [4.3.0] — 2026-01-11

### Added

- Auto-complete debounce delay configuration.
- Additional inline-completion options in Claude mode.
- Conversation continuation in Claude mode.

### Changed

- Settings dialog hides Claude-specific options when Claude mode is off.
- NBI sidebar moved to the left side of the JupyterLab UI.

### Fixed

- Auto-complete tab-state handling.

## [4.2.1] — 2026-01-06

### Changed

- Project rebrand from "JUI" to "NBI" (`@notebook-intelligence/notebook-intelligence`).

## [4.2.0] — 2026-01-06

### Changed

- Notebook tool calls (e.g., cell execution) now require explicit user approval instead of being auto-allowed.

### Fixed

- Improved error handling and message-handler disconnect.
- Claude settings font color and UI state when toggling Claude mode.

## [4.1.2] — 2026-01-05

### Fixed

- Lock-handling in long-running Claude sessions.

## [4.1.1] — 2026-01-04

### Fixed

- Claude mode reliability (multiple cleanup commits).

## [4.1.0] — 2026-01-03

### Added

- Plan mode for Claude.
- Custom message for the Bash tool.

### Changed

- Claude session timeout raised to 30 minutes.
- Improved AskUserQuestion styling.

### Fixed

- Current-directory context and chat-history handling.

## [4.0.0] — 2026-01-01

### Added

- **Claude mode** — first-class integration with [Claude Code](https://code.claude.com/), including:
  - Claude Code-backed Agent Chat UI, inline chat, and auto-complete.
  - Claude Code tools, skills, MCP servers, and custom commands available inside JupyterLab.
  - Claude session resume from `~/.claude/projects/`.
- Honor `c.ServerApp.base_url` for all extension routes.

### Changed

- Settings UI restructured around Claude vs default mode.
- WebSocket connection reliability improvements.

[unreleased]: https://github.com/plmbr/notebook-intelligence/compare/v5.0.0...HEAD
[5.0.0]: https://github.com/plmbr/notebook-intelligence/compare/v4.8.0...v5.0.0
[4.8.0]: https://github.com/plmbr/notebook-intelligence/compare/v4.7.0...v4.8.0
[4.7.0]: https://github.com/plmbr/notebook-intelligence/compare/v4.6.0...v4.7.0
[4.6.0]: https://github.com/plmbr/notebook-intelligence/compare/v4.5.0...v4.6.0
[4.5.0]: https://github.com/plmbr/notebook-intelligence/compare/v4.4.0...v4.5.0
[4.4.0]: https://github.com/plmbr/notebook-intelligence/compare/v4.3.2...v4.4.0
[4.3.2]: https://github.com/plmbr/notebook-intelligence/compare/v4.3.1...v4.3.2
[4.3.1]: https://github.com/plmbr/notebook-intelligence/compare/v4.3.0...v4.3.1
[4.3.0]: https://github.com/plmbr/notebook-intelligence/compare/v4.2.1...v4.3.0
[4.2.1]: https://github.com/plmbr/notebook-intelligence/compare/v4.2.0...v4.2.1
[4.2.0]: https://github.com/plmbr/notebook-intelligence/compare/v4.1.2...v4.2.0
[4.1.2]: https://github.com/plmbr/notebook-intelligence/compare/v4.1.1...v4.1.2
[4.1.1]: https://github.com/plmbr/notebook-intelligence/compare/v4.1.0...v4.1.1
[4.1.0]: https://github.com/plmbr/notebook-intelligence/compare/v4.0.0...v4.1.0
[4.0.0]: https://github.com/plmbr/notebook-intelligence/releases/tag/v4.0.0

## Versioning policy

- **Major (X.0.0)** — backward-incompatible changes to traitlets, environment variables, REST routes, or on-disk file formats. Major releases are accompanied by a migration note in this file.
- **Minor (4.Y.0)** — new features and traitlets. Existing configuration continues to work.
- **Patch (4.5.Z)** — bug fixes only.

Deprecations land in a minor release with a warning at startup, and are removed no earlier than the next major release.
