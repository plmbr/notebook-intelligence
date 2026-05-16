---
layout: page
title: Admin and policy
subtitle: Pin providers, lock endpoints, and govern Skills + Plugins from environment variables — built for managed JupyterHub.
permalink: /admin/
---

NBI is built to be deployable across a team without surprising users. Every user-facing toggle has a corresponding `NBI_*` environment variable that lets a platform admin decide its value before anyone signs in.

## The policy triad

For boolean capabilities, each policy takes one of three values:

| Value | Meaning |
|---|---|
| `force-on` | Always enabled. The user's Settings dialog shows the control locked on. |
| `force-off` | Always disabled. The user's Settings dialog shows the control locked off. |
| `user-choice` | Honor the user's `config.json` (default). |

For string-valued settings (provider, model, endpoint) the env var sets the value and the UI control becomes read-only.

## Policy categories

- **Mode and feature flags.** `NBI_CLAUDE_MODE_POLICY`, `NBI_CLAUDE_CONTINUE_CONVERSATION_POLICY`, `NBI_CLAUDE_CODE_TOOLS_POLICY`, `NBI_CLAUDE_JUPYTER_UI_TOOLS_POLICY`, `NBI_EXPLAIN_ERROR_POLICY`, `NBI_OUTPUT_FOLLOWUP_POLICY`, `NBI_OUTPUT_TOOLBAR_POLICY`, `NBI_STORE_GITHUB_ACCESS_TOKEN_POLICY`.
- **Provider locks.** `NBI_CHAT_MODEL_PROVIDER`, `NBI_CHAT_MODEL_ID`, `NBI_INLINE_COMPLETION_MODEL_PROVIDER`, `NBI_INLINE_COMPLETION_MODEL_ID`, `NBI_CLAUDE_CHAT_MODEL`, `NBI_CLAUDE_INLINE_COMPLETION_MODEL`.
- **Anthropic endpoint pinning.** `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` (read by the Claude SDK directly, propagated by NBI).
- **Skills and Plugins management.** `NBI_SKILLS_MANIFEST` (org-managed YAML manifest URL or path), `NBI_SKILLS_MANIFEST_INTERVAL`, `NBI_SKILLS_MANIFEST_TOKEN`, `NBI_ALLOW_GITHUB_SKILL_IMPORT`, `NBI_CLAUDE_PLUGINS_MANAGEMENT_POLICY`.
- **Provider gating.** `NBI_DISABLED_PROVIDERS` (comma-separated list).

## Fail-loud resolvers

Every `NBI_*_POLICY` env var is parsed strictly. A typo like `force_on` (underscore instead of hyphen) raises at server startup — no silent fallback. That keeps misconfigured production deployments from looking superficially correct.

## Skills manifest

An organization can curate a set of Claude Skills via a YAML manifest:

```yaml
skills:
  - url: https://github.com/your-org/data-skills/tree/main/skills/eda
    scope: user
  - url: https://github.com/your-org/data-skills/tree/main/skills/ml-recipes
    scope: user
```

Set `NBI_SKILLS_MANIFEST=https://your-org/skills.yaml` (or a filesystem path). NBI's reconciler installs every Skill at startup and re-syncs every 24h. Managed Skills are read-only in the UI — users can't edit, rename, or delete them; if they try to remove one, the reconciler restores it on the next pass.

## Reference

- [Full admin guide](https://github.com/notebook-intelligence/notebook-intelligence/blob/main/docs/admin-guide.md) — every env var, every default, every interaction.
- [Security policy](https://github.com/notebook-intelligence/notebook-intelligence/blob/main/SECURITY.md) — disclosure, threat model, supply-chain posture.
- [Privacy](https://github.com/notebook-intelligence/notebook-intelligence/blob/main/PRIVACY.md) — what NBI sends where.

<p style="margin-top: var(--space-10);"><a class="btn btn--primary" href="{{ '/install/' | relative_url }}">Install NBI</a></p>
