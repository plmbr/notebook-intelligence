---
layout: page
title: Skills & Plugins
subtitle: Author and import Claude Skills and Plugins. Sync an org manifest across every user.
permalink: /features/skills-plugins/
---

## Claude Skills

A Claude Skill is a bundle of instructions, allowed tools, and helper files that an agent can invoke. As of 5.0.0, NBI's Skills tab is a top-level Settings tab visible in any mode (with a hint banner when Claude mode is off).

- **Author inline.** Create a new Skill, edit its `SKILL.md` and helper files without leaving the lab.
- **Import from GitHub.** Drop a `github.com/owner/repo/tree/main/skills/<name>` URL into the import dialog; NBI fetches the tarball, validates the bundle, and installs it under `~/.jupyter/skills/`. Optional **Track upstream** checkbox surfaces a per-skill Sync button and a panel-level "Sync tracking skills".
- **Org-managed manifest.** Point `NBI_SKILLS_MANIFEST` at one or more YAML manifest files or URLs (comma-separated for multiple). NBI's reconciler installs every Skill at startup and re-checks every 24h. Managed Skills are read-only in the UI — users can't edit, rename, or delete them, and the reconciler restores any that get removed.

## Claude MCP Servers

A separate top-level tab in 5.0.0 manages the user, project, and local-scope MCP entries Claude Code reads from `~/.claude.json` and `<project>/.mcp.json`. Independent of the existing NBI MCP tab; the two never appear at the same time.

- **Per-workspace enable / disable.** Toggle individual MCP entries on / off without removing them.
- **JSON-paste path.** Paste a Claude / Cursor / VS Code MCP config blob; NBI parses, validates, and pre-fills the form.
- **Admin policy.** `NBI_CLAUDE_MCP_MANAGEMENT_POLICY=force-off` hides the tab and 403s `/claude-mcp/*` routes.

## Claude Plugins

Claude Plugins are install-and-go bundles published to marketplaces. NBI's Plugins panel wraps the `claude plugin` CLI:

- **Install, uninstall, enable, disable.** From a marketplace URL or a GitHub repo.
- **Marketplace add / remove.** Manage which marketplaces are visible to Claude.
- **Marketplace picker.** Browse the configured marketplaces inline; entries show source repo, version, and description.
- **Per-plugin Update button.** Surfaces when a newer version is available upstream.
- **Project vs user scope.** Plugins installed to a project root are isolated to that workspace.
- **Admin policies.** `NBI_CLAUDE_PLUGINS_MANAGEMENT_POLICY` for the whole tab; `NBI_ALLOW_GITHUB_PLUGIN_IMPORT` for marketplace sources resolving as GitHub URLs.

## Manifest example

```yaml
skills:
  - url: https://github.com/your-org/data-skills/tree/main/skills/eda
    name: eda
    scope: user
  - url: https://github.com/your-org/data-skills/tree/main/skills/ml-recipes
    scope: user
```

## Reference

- [NBI Skills documentation](https://github.com/plmbr/notebook-intelligence/blob/main/docs/skills.md)
- [Claude Skills SDK](https://docs.claude.com/en/docs/claude-code/skills)
- [Claude Plugins](https://docs.claude.com/en/docs/claude-code/plugins)

<p style="margin-top: var(--space-10);"><a class="btn btn--primary" href="{{ '/install/' | relative_url }}">Install NBI</a></p>
