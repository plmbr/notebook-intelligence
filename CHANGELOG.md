# Changelog

All notable changes to Notebook Intelligence are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) starting with 4.0.0.

For each release we list user-facing changes grouped as **Added**, **Changed**, **Fixed**, and **Removed**. Commits are squashed into the change that motivated them; the full git log remains the source of truth for low-level history.

<!-- <START NEW CHANGELOG ENTRY> -->

## [Unreleased]

### Added

- **Skills as a top-level Settings tab** (#224). Promoted from a Claude-mode sub-tab; the tab is now visible in any mode, with a hint banner when Claude mode is off. New admin policy `skills_management_policy` (env `NBI_SKILLS_MANAGEMENT_POLICY`); `force-off` hides the tab, returns HTTP 403 from every `/notebook-intelligence/skills/*` route, and suppresses the managed-skills reconciler.
- **Claude MCP Servers tab** (#225) for managing the user, project, and local-scope MCP entries Claude Code reads from `~/.claude.json` and `<project>/.mcp.json`. Independent of the existing NBI MCP tab; the two never appear at the same time. New admin policy `claude_mcp_management_policy` (env `NBI_CLAUDE_MCP_MANAGEMENT_POLICY`).
- **Claude Plugins tab** (#226) wrapping `claude plugin` for install / uninstall / enable / disable / marketplace add. New admin policies `claude_plugins_management_policy` (env `NBI_CLAUDE_PLUGINS_MANAGEMENT_POLICY`) and `allow_github_plugin_import` (env `NBI_ALLOW_GITHUB_PLUGIN_IMPORT`), the latter mirroring the existing `allow_github_skill_import` knob for marketplace sources.
- **GitHub auth for plugin marketplace add**. Marketplace sources that resolve as GitHub URLs or `owner/repo` shorthand reuse Skills' `GITHUB_TOKEN` / `GH_TOKEN` / `gh auth token` precedence; tokens are injected into the `claude plugin marketplace add` subprocess via env, never argv.
- **Launcher tiles for opencode, Pi, and GitHub Copilot CLI** (#268), with a follow-on for **OpenAI Codex**. Each tile appears when the corresponding binary is on `PATH` and opens a Jupyter terminal at the file-browser's current directory. CLI path overrides: `NBI_OPENCODE_CLI_PATH`, `NBI_PI_CLI_PATH`, `NBI_GITHUB_COPILOT_CLI_PATH`, `NBI_CODEX_CLI_PATH`. The capabilities response gains matching `*_cli_available` booleans.
- **Claude Code launcher tile is no longer gated by Claude chat mode** (#239); it appears whenever the `claude` CLI is on `PATH`.
- **Dynamic GitHub Copilot model discovery** (#269). NBI now queries `https://api.githubcopilot.com/models` on each Copilot token refresh and the chat-model dropdown rebuilds from the live response, falling back to a hardcoded list on transient failure.
- **Newer GitHub Copilot chat models** added to the fallback list (#255).
- **Skill GitHub archive cap raised to 100 MB**, configurable (#257). New traitlet `skill_max_archive_mb` (env `NBI_SKILL_MAX_ARCHIVE_MB`); `0` disables the cap.
- **`additional_skipped_workspace_directories` accepted in NBI `config.json`** (#241), layered additively on top of the existing traitlet, env, and env-prefix layers so a per-user override can extend (rather than replace) the org-wide list.
- **Real progress feedback during long Claude tasks** (#254). The chat sidebar shows an elapsed-time counter, a heartbeat-driven pulse with a "may be slow" copy flip after 30 seconds, and inline tool-call narration.
- **"New chat session" button** in the chat sidebar header restarts the Claude SDK client, mirroring the `/clear` slash command (#246).
- **Terminal drag-drop file attach** with `@`-mention or shell-escaped raw modes and a per-terminal toolbar toggle (#256). New admin policy `NBI_TERMINAL_DRAG_DROP_POLICY`; tunables `NBI_UPLOAD_MAX_MB` (default `50`) and `NBI_UPLOAD_RETENTION_HOURS` (default `24`) govern the shared upload-staging endpoint used by both terminal drops and chat-sidebar attachments.
- **Hover preview for image context thumbnails** in the chat sidebar (#267).

### Changed

- Settings tabs are now an ARIA tablist with arrow-key navigation (#206).
- Accessibility pass across the chat sidebar and popovers covering keyboard and screen-reader behavior (#205).
- Chat-input footer icons reworded for clarity; the gear button gains a `title` attribute (#271).
- Cell-tool descriptions mention zero-based indexing so models pick the right cell (#265).

### Fixed

- Websocket writes from worker threads no longer raise `BufferError` after `/clear` or "new chat" on Python 3.13+ (#270). All emitter writes now route through `tornado.IOLoop.call_soon_threadsafe`.
- Cell tools follow the active notebook when the user switches tabs (#253).
- `is_connected()` stabilized against the Claude worker-spawn resurrection race (#250).
- Persisted Claude model now displays after a JupyterLab restart (#244).
- `/clear` no longer duplicated in the `@`-mention autocomplete (#243).
- `@`-mention picker refreshes when workspace files change (#251) and closes on Escape from the search input (#266).
- Notebook-toolbar prompt textarea focuses when the popover opens (#240); the update button works outside Claude mode (#238).
- Inline chat anchors to the cursor line (#191).
- Disabled send button is styled neutrally instead of as a primary action (#276); Claude tool-result check renders on the right of its label (#277).
- Plugin Settings row shows the plugin name even when the CLI returns only `id` (#280).

### Internal

- CVE-driven dependency upgrades (#197); `react-icons` bumped to `~5.6.0` (#245).
- Galata-based Playwright UI test suite scaffolded (#207) and expanded with user-flow specs covering the chat sidebar, notebook toolbar, cell outputs, and the launcher (#272).
- Contributor docs cover the traitlet vs env var vs config-file decision (#242).

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

[unreleased]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.8.0...HEAD
[4.8.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.7.0...v4.8.0
[4.7.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.6.0...v4.7.0
[4.6.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.5.0...v4.6.0
[4.5.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.4.0...v4.5.0
[4.4.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.3.2...v4.4.0
[4.3.2]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.3.1...v4.3.2
[4.3.1]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.3.0...v4.3.1
[4.3.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.2.1...v4.3.0
[4.2.1]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.2.0...v4.2.1
[4.2.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.1.2...v4.2.0
[4.1.2]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.1.1...v4.1.2
[4.1.1]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.1.0...v4.1.1
[4.1.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.0.0...v4.1.0
[4.0.0]: https://github.com/notebook-intelligence/notebook-intelligence/releases/tag/v4.0.0

## Versioning policy

- **Major (X.0.0)** — backward-incompatible changes to traitlets, environment variables, REST routes, or on-disk file formats. Major releases are accompanied by a migration note in this file.
- **Minor (4.Y.0)** — new features and traitlets. Existing configuration continues to work.
- **Patch (4.5.Z)** — bug fixes only.

Deprecations land in a minor release with a warning at startup, and are removed no earlier than the next major release.
