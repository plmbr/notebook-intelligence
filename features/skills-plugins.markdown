---
layout: page
title: Skills & Plugins
subtitle: Author and import Claude Skills and Plugins. Sync an org manifest across every user.
permalink: /features/skills-plugins/
---

## Claude Skills

A Claude Skill is a bundle of instructions, allowed tools, and helper files that an agent can invoke. NBI manages them from a Skills tab in Settings.

- **Author inline.** Create a new Skill, edit its `SKILL.md` and helper files without leaving the lab.
- **Import from GitHub.** Drop a `github.com/owner/repo/tree/main/skills/<name>` URL into the import dialog; NBI fetches the tarball, validates the bundle, and installs it under `~/.jupyter/skills/`.
- **Org-managed manifest.** Point `NBI_SKILLS_MANIFEST` at a YAML manifest file or URL. NBI's reconciler installs every Skill in the manifest at startup and re-checks every 24h. Managed Skills are read-only in the UI — users can't edit, rename, or delete them, and the reconciler restores any that get removed.

## Claude Plugins

Claude Plugins are install-and-go bundles published to marketplaces. NBI's Plugins panel wraps the `claude plugin` CLI:

- **Install, uninstall, enable, disable.** From a marketplace URL or a GitHub repo.
- **Marketplace add/remove.** Manage which marketplaces are visible to Claude.
- **Project vs user scope.** Plugins installed to a project root are isolated to that workspace.

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

- [NBI Skills documentation](https://github.com/notebook-intelligence/notebook-intelligence/blob/main/docs/skills.md)
- [Claude Skills SDK](https://docs.claude.com/en/docs/claude-code/skills)
- [Claude Plugins](https://docs.claude.com/en/docs/claude-code/plugins)

<p style="margin-top: var(--space-10);"><a class="btn btn--primary" href="{{ '/install/' | relative_url }}">Install NBI</a></p>
