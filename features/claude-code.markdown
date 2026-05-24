---
layout: page
title: Claude Code
subtitle: First-class Claude Code inside JupyterLab — sessions, Skills, Plugins, MCP, and agent-mode notebook editing.
permalink: /features/claude-code/
---

NBI's deepest integration is with [Claude Code](https://docs.claude.com/en/docs/claude-code). When Claude mode is on, the chat sidebar, inline chat, and notebook agent all route through the Claude Code SDK (`claude-agent-sdk`).

## What you get

- **Session resume.** A Claude Code tile on the JupyterLab launcher opens a picker listing every session in `~/.claude/projects/`. Resume a transcript or start a new session scoped to a directory you pick. The tile is no longer gated by Claude chat mode — it appears whenever the `claude` CLI is on `PATH`.
- **Agent-mode notebook editing.** The agent can create notebooks, add and edit cells, run them, read the output, and fix errors without leaving the document.
- **Real progress feedback** during long Claude turns. An elapsed-time counter, a heartbeat-driven pulse with a "may be slow" copy flip after 30 seconds, and inline tool-call narration so the sidebar reflects what the agent is doing.
- **Open files refresh on disk change.** When Claude edits a file you have open, the tab reverts to the disk version automatically. Tabs with unsaved local edits are skipped. Toggle in **NBI Settings → External changes**.
- **Workspace files as @-mention pointers.** Attaching a file ships an `@<path>` pointer instead of inlining contents, so images, large files, and notebooks (cell-aware) all work where the older path silently truncated them.
- **Tools, Skills, Plugins, MCP.** Everything the standalone Claude CLI can use is available from inside JupyterLab — see [Skills &amp; Plugins]({{ '/features/skills-plugins/' | relative_url }}) and [MCP servers]({{ '/features/mcp/' | relative_url }}).
- **Cell output actions.** Right-click a cell output for **Explain**, **Ask**, or **Troubleshoot** quick actions that open the chat with the output already attached as context.
- **Terminal drag-drop file attach** with `@`-mention or shell-escaped raw modes. Shift inverts the mode for one drop.
- **New chat session** button next to the gear restarts the SDK client without typing `/clear`.
- **AGENTS.md support.** When a project root contains an `AGENTS.md`, NBI appends it under the system prompt's "Additional Guidelines" alongside the existing ruleset injection.

## Setup

Install the Claude Code CLI, sign in, and turn on Claude mode in NBI Settings:

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

If `claude` is not on your `PATH`, set `NBI_CLAUDE_CLI_PATH` to the full path of the binary.

## Configuration

```json
{
  "claude_settings": {
    "enabled": true,
    "chat_model": "claude-sonnet-4-6",
    "inline_completion_model": "claude-haiku-4-5-20251001",
    "continue_conversation": true
  }
}
```

Or via environment variables for managed deployments — see [admin policies]({{ '/admin/' | relative_url }}) for the full list.

## Reference

- [Claude Code documentation](https://docs.claude.com/en/docs/claude-code) (Anthropic)
- [NBI Claude mode reference](https://github.com/plmbr/notebook-intelligence/blob/main/README.md#claude-mode)
- [Skills documentation](https://github.com/plmbr/notebook-intelligence/blob/main/docs/skills.md)

<p style="margin-top: var(--space-10);"><a class="btn btn--primary" href="{{ '/install/' | relative_url }}">Install NBI</a></p>
