---
layout: page
title: MCP servers
subtitle: Expose your own tools, databases, and APIs to the chat over the Model Context Protocol.
permalink: /features/mcp/
---

The [Model Context Protocol](https://modelcontextprotocol.io/) is a small, well-specified way for an LLM to call external tools. NBI manages MCP servers from inside the lab — add, remove, enable, disable — and routes their tools into the agent's toolbox.

## What you get

- **In-lab management.** A dedicated panel in Settings lists every MCP server, transport (stdio, SSE, HTTP), and status. Add a new one without dropping to a terminal.
- **Per-server enable/disable.** Toggle a server off without uninstalling it, useful when iterating on a flaky local server.
- **HTTPS-only for remote.** SSE and HTTP transports require `https://` URLs; flag-smuggling guards reject malformed env / header inputs at add-time.

## Add a server

From Settings → MCP, click **Add server** and provide a name, transport, and command (for stdio) or URL (for SSE/HTTP). Example for the official Postgres MCP server:

```json
{
  "name": "postgres",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/analytics"]
}
```

For an HTTP/SSE server hosted internally:

```json
{
  "name": "internal-search",
  "transport": "http",
  "url": "https://mcp.internal/search",
  "headers": { "Authorization": "Bearer ${MY_TOKEN}" }
}
```

## Reference

- [Model Context Protocol spec](https://modelcontextprotocol.io/specification)
- [Anthropic MCP server registry](https://github.com/modelcontextprotocol/servers)
- [NBI MCP admin policy]({{ '/admin/' | relative_url }})

<p style="margin-top: var(--space-10);"><a class="btn btn--primary" href="{{ '/install/' | relative_url }}">Install NBI</a></p>
