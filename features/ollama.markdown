---
layout: page
title: Ollama
subtitle: Local chat and auto-complete against models you already pulled. Fully offline.
permalink: /features/ollama/
---

NBI talks to a local [Ollama](https://ollama.com/) server for chat and inline completion. No external API calls; all inference stays on your machine.

## What you get

- **Local chat.** Any Ollama chat model with tool-calling support drives the chat sidebar. Llama 3.x, Qwen, Mistral, and others work out of the box.
- **Local inline completion.** A separate allowlist of completion-tuned models powers tab-complete. Smaller, faster models like `qwen2.5-coder:7b` are the sweet spot.
- **Zero egress.** Useful for air-gapped environments, sensitive data, or regulated industries.

## Setup

Install Ollama and pull a chat-capable model:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3:latest
ollama pull qwen2.5-coder:7b
```

Then pick **Ollama** as the chat provider in NBI Settings.

## Configuration

```json
{
  "chat_model": { "provider": "ollama", "model": "llama3:latest" },
  "inline_completion_model": { "provider": "ollama", "model": "qwen2.5-coder:7b" }
}
```

NBI talks to the default Ollama endpoint at `http://localhost:11434`. Set `OLLAMA_HOST` if you've moved it.

<p style="margin-top: var(--space-10);"><a class="btn btn--primary" href="{{ '/install/' | relative_url }}">Install NBI</a></p>
