---
layout: page
title: About
subtitle: A JupyterLab extension for agentic AI — Claude Code first, with Copilot, Ollama, and OpenAI-compatible models alongside.
permalink: /about/
---

Notebook Intelligence (NBI) is a JupyterLab extension that brings agentic AI coding into the notebook. It runs Claude Code as a first-class provider with sessions, Skills, Plugins, and MCP servers, and ships with GitHub Copilot, Ollama, and any OpenAI- or LiteLLM-compatible endpoint as drop-in alternates.

NBI works the way JupyterLab does. Chat lives in a sidebar with `@`-mention participants. Inline chat opens on any cell with <kbd>Ctrl</kbd>+<kbd>G</kbd> or <kbd>Cmd</kbd>+<kbd>G</kbd>. Auto-complete suggests code as you type. Agent mode goes further: it creates notebooks, edits cells, runs them, and fixes errors without leaving the document.

The extension is built to be extended. Connect [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) servers to expose your own tools, databases, and APIs to the chat. Manage Claude Skills and Plugins from the UI, or sync an organization-wide manifest so every user in the lab lands with the same set on install. Drop markdown files into `~/.jupyter/nbi/rules/` to inject conventions, style guides, or guardrails into every prompt.

For administrators, NBI ships policy controls that lock specific providers, models, and endpoints via environment variables. A platform team can decide what a managed JupyterHub allows before anyone signs in — each capability has a `force-on` / `force-off` / `user-choice` triad with a matching `NBI_*_POLICY` env var.

NBI is open source and BSD-licensed. It is maintained by [Mehmet Bektaş](https://github.com/mbektas) and a growing group of contributors from the Jupyter community. The codebase lives at [github.com/notebook-intelligence/notebook-intelligence](https://github.com/notebook-intelligence/notebook-intelligence).
