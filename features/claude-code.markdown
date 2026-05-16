---
layout: page
title: Claude Code
subtitle: First-class Claude Code inside JupyterLab — sessions, Skills, Plugins, MCP, and agent-mode notebook editing.
permalink: /features/claude-code/
---

NBI's deepest integration is with [Claude Code](https://docs.claude.com/en/docs/claude-code). When Claude mode is on, the chat sidebar, inline chat, and notebook agent all route through the Claude Code SDK (`claude-agent-sdk`).

## What you get

- **Session resume.** A Claude Code tile on the JupyterLab launcher opens a picker listing every session in `~/.claude/projects/`. Resume a transcript or start a new session scoped to the file browser's current directory.
- **Agent-mode notebook editing.** The agent can create notebooks, add and edit cells, run them, read the output, and fix errors without leaving the document.
- **Tools, Skills, Plugins, MCP.** Everything the standalone Claude CLI can use is available from inside JupyterLab — see [Skills &amp; Plugins]({{ '/features/skills-plugins/' | relative_url }}) and [MCP servers]({{ '/features/mcp/' | relative_url }}).
- **Cell output actions.** Right-click a cell output for **Explain**, **Ask**, or **Troubleshoot** quick actions that open the chat with the output already attached as context.
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
- [NBI Claude mode reference](https://github.com/notebook-intelligence/notebook-intelligence/blob/main/README.md#claude-mode)
- [Skills documentation](https://github.com/notebook-intelligence/notebook-intelligence/blob/main/docs/skills.md)

<p style="margin-top: var(--space-10);"><a class="btn btn--primary" href="{{ '/install/' | relative_url }}">Install NBI</a></p>
