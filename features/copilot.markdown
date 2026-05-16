---
layout: page
title: GitHub Copilot
subtitle: Use any Copilot chat or completion model from inside JupyterLab.
permalink: /features/copilot/
---

NBI was originally built around GitHub Copilot, and Copilot remains a first-class provider when Claude mode is off. Chat and inline completion both go through Copilot's chat-completions endpoint.

## What you get

- **Device-flow auth.** Sign in once from NBI Settings — the same GitHub device-flow you use in VS Code. NBI stores the refresh token in `~/.jupyter/nbi/copilot.json`.
- **Model picker.** All Copilot chat models the API exposes appear in the model dropdown, including the latest GPT and Anthropic options Copilot routes for you.
- **Inline completion.** Tab-completion as you type, with configurable debounce delay and a separate model from chat.
- **Slash commands.** `/explain`, `/fix`, `/troubleshoot`, `/newNotebook`, `/newPythonFile` work out of the box.

## Setup

Open the chat sidebar, click **Sign in with GitHub**, and follow the device-flow prompt. NBI stores the access token at `~/.jupyter/nbi/copilot.json` (set `NBI_STORE_GITHUB_ACCESS_TOKEN_POLICY=force-off` to keep it in-memory only).

## Configuration

```json
{
  "chat_model": { "provider": "github-copilot", "model": "gpt-4o" },
  "inline_completion_model": { "provider": "github-copilot", "model": "gpt-4o-mini" }
}
```

## Reference

- [GitHub Copilot documentation](https://docs.github.com/en/copilot)

<p style="margin-top: var(--space-10);"><a class="btn btn--primary" href="{{ '/install/' | relative_url }}">Install NBI</a></p>
