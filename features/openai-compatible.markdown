---
layout: page
title: OpenAI-compatible
subtitle: Point NBI at any OpenAI- or LiteLLM-compatible endpoint with a base URL, model ID, and key.
permalink: /features/openai-compatible/
---

NBI's OpenAI-compatible provider speaks the Chat Completions API. Anything that exposes that API works — Anthropic via the direct API, vLLM, [LiteLLM](https://github.com/BerriAI/litellm), TGI, llama.cpp's HTTP server, hosted services, your own gateway.

## What you get

- **Bring your own endpoint.** Provide a base URL, an API key, and a model ID. NBI handles the rest.
- **Tool calling and inline completion.** Tool calling works wherever the upstream server supports it (vLLM with `--enable-auto-tool-choice`, LiteLLM with native or translated tool calls, etc.).
- **Per-pod overrides.** Useful for centralized gateways: lock the base URL at the JupyterHub level with `NBI_OPENAI_BASE_URL` and let users only pick the model.

## Configuration

```json
{
  "chat_model": {
    "provider": "openai-compatible",
    "model": "gpt-oss-120b",
    "base_url": "https://your-gateway.internal/v1",
    "api_key": "sk-..."
  }
}
```

## Reference

- [LiteLLM proxy docs](https://docs.litellm.ai/docs/simple_proxy)
- [vLLM tool-calling guide](https://docs.vllm.ai/en/latest/features/tool_calling.html)

<p style="margin-top: var(--space-10);"><a class="btn btn--primary" href="{{ '/install/' | relative_url }}">Install NBI</a></p>
