---
layout: page
title: Install
subtitle: Pip-install into any JupyterLab 4 environment, then configure your provider of choice.
permalink: /install/
---

## Prerequisites

- **Python 3.10 or newer.** NBI follows Jupyter's supported-Python window.
- **JupyterLab 4.x.** NBI is a labextension, so it ships pre-built and loads on the first JupyterLab restart.
- A provider — at least one of: Claude Code CLI, GitHub Copilot account, a running Ollama server, or an OpenAI-compatible endpoint.

## Install the extension

```bash
pip install notebook-intelligence
```

Then restart JupyterLab. The NBI sidebar appears on the left.

For conda or pixi-managed environments, install into the same env that runs `jupyter lab`. NBI does not need a separate Python kernel.

## Pick a provider

NBI supports four model providers; you can configure one or several. Open **Settings → NBI** and follow the instructions for your chosen path.

<details>
  <summary>Claude Code (recommended)</summary>

Install the Claude Code CLI and sign in:

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

If `claude` is not on your `PATH` (for example, in a non-default Node install), set `NBI_CLAUDE_CLI_PATH` to the full path of the binary before starting JupyterLab.

In NBI Settings, toggle **Claude mode** on and pick a chat model.

</details>

<details>
  <summary>GitHub Copilot</summary>

In the NBI chat sidebar, click **Sign in with GitHub** and follow the device-flow prompt in your browser. NBI stores the access token at `~/.jupyter/nbi/copilot.json`. Set `NBI_STORE_GITHUB_ACCESS_TOKEN_POLICY=force-off` to keep it in-memory only.

</details>

<details>
  <summary>Ollama</summary>

Install Ollama and pull a chat-capable model:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3:latest
```

Then pick **Ollama** as the chat provider in Settings. NBI talks to the default Ollama endpoint at `http://localhost:11434`. If Ollama runs elsewhere, set `OLLAMA_HOST`.

</details>

<details>
  <summary>OpenAI-compatible (vLLM, LiteLLM, hosted)</summary>

In Settings, pick **OpenAI-compatible** and provide:

- a **base URL** (e.g. `https://your-gateway.internal/v1`)
- a **model ID** (e.g. `gpt-oss-120b`)
- an **API key**

The base URL must speak the Chat Completions API. vLLM, LiteLLM, TGI, and llama.cpp's HTTP server all qualify; anything in front of a real OpenAI-compatible LLM will work.

</details>

## First run

1. **Open the chat sidebar.** The NBI icon appears on the left activity bar.
2. **Send a prompt.** Type a question and hit return. The first response confirms your provider is wired up.
3. **Try inline chat.** Click into a code cell and hit <kbd>Cmd</kbd>+<kbd>I</kbd> (or <kbd>Ctrl</kbd>+<kbd>I</kbd> on Linux/Windows) to open the inline popover.
4. **Try agent mode.** Click the sparkle icon on the active notebook toolbar to scope a generation to that notebook. The agent will plan, write, and run cells.

## Troubleshooting

If something doesn't work, check:

- `jupyter server extension list` — `notebook_intelligence` should appear under "OK".
- `jupyter labextension list` — `@notebook-intelligence/notebook-intelligence` should be listed as enabled.
- The JupyterLab terminal output where you ran `jupyter lab`. NBI logs server-side errors there.

For deeper issues, see the [troubleshooting guide](https://github.com/notebook-intelligence/notebook-intelligence/blob/main/docs/troubleshooting.md) in the repo or [open an issue](https://github.com/notebook-intelligence/notebook-intelligence/issues).
