---
layout: page
title: Providers
subtitle: Pick one, or wire up several. NBI keeps a separate setting for chat and inline completion, so you can mix and match.
permalink: /providers/
---

## At a glance

{% capture check %}<span class="support support--yes" role="img" aria-label="Supported"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg></span>{% endcapture %}
{% capture nope %}<span class="support support--no" role="img" aria-label="Not supported">&mdash;</span>{% endcapture %}

<div class="support-table-wrap" tabindex="0" role="region" aria-label="Provider feature comparison">
  <table class="support-table">
    <thead>
      <tr>
        <th class="support-table__th--left">Provider</th>
        <th class="support-table__th--left">Auth</th>
        <th>Chat &amp; completion</th>
        <th>Offline</th>
        <th>Agent mode</th>
        <th>MCP</th>
        <th>Skills</th>
        <th>Plugins</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <th scope="row">Claude Code</th>
        <td class="support-table__td--text">Anthropic CLI sign-in</td>
        <td>{{ check }}</td>
        <td>{{ nope }}</td>
        <td>{{ check }}</td>
        <td>{{ check }}</td>
        <td>{{ check }}</td>
        <td>{{ check }}</td>
      </tr>
      <tr>
        <th scope="row">GitHub Copilot</th>
        <td class="support-table__td--text">GitHub device flow</td>
        <td>{{ check }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
      </tr>
      <tr>
        <th scope="row">Ollama</th>
        <td class="support-table__td--text">None (local)</td>
        <td>{{ check }}</td>
        <td>{{ check }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
      </tr>
      <tr>
        <th scope="row">OpenAI-compatible</th>
        <td class="support-table__td--text">Bearer token</td>
        <td>{{ check }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
        <td>{{ nope }}</td>
      </tr>
    </tbody>
  </table>
</div>

Every provider supports **chat and inline completion** — that's the floor. Beyond that, the deeper agent surface (agent-mode notebook editing, MCP servers, Skills, Plugins) is Claude Code only by design: those features integrate with the Claude Code CLI's session and tool model.

If you need offline operation, **Ollama** is the only path. If you need agentic behavior, **Claude Code** is the only path. Most teams pick one for chat and a different one for inline completion — see below.

## When to pick which

**Use Claude Code if** you want the full agent surface — sessions, Skills, Plugins, MCP, agent-mode notebook editing. Claude Code is the deepest integration and the only path to all of those features.

**Use GitHub Copilot if** you already pay for it and want a familiar chat + inline completion experience. Good model choice via Copilot's routing, no separate API key to manage.

**Use Ollama if** you need everything to stay local. Air-gapped environments, sensitive data, or regulated industries. Pick a smaller completion-tuned model for inline completion to keep latency manageable.

**Use OpenAI-compatible if** you have an existing LLM gateway (LiteLLM, vLLM, an internal proxy) or want to use a non-Anthropic frontier model directly. Particularly useful for managed JupyterHub deployments where a single gateway sees every request.

## Mixing providers

NBI keeps separate settings for **chat** and **inline completion** so you can mix. Common combinations:

- Claude Code for chat, Copilot for inline (lighter latency on the per-keystroke path).
- OpenAI-compatible for chat (your team's gateway), Ollama for inline (local, fast).
- Claude Code for everything if you want one consistent agent throughout.

## Locking the choice

For deployments where you don't want users picking arbitrary providers, environment-variable policies pin the selection at the JupyterHub or container level. See [Admin]({{ '/admin/' | relative_url }}) for the policy taxonomy.

<p style="margin-top: var(--space-10);"><a class="btn btn--primary" href="{{ '/install/' | relative_url }}">Install NBI</a></p>
