---
layout: post
title: "Codex in the chat sidebar: NBI's experimental ACP agent mode"
date: 2026-09-07 06:00:00 -0700
permalink: /blog/codex-acp-agent-mode/
description: "NBI 5.4 adds a second agent mode that drives an external coding agent over the Agent Client Protocol, with OpenAI Codex as the first agent. Here is how to turn it on, what a turn looks like, how approvals and Codex's sandbox work together, and what it does not do yet."
---

[Notebook Intelligence](https://github.com/plmbr/notebook-intelligence) (NBI) is an AI coding assistant and extensible AI framework for JupyterLab.

OpenAI Codex already has two ways into NBI. The launcher's Coding Agent section has a Codex tile that starts the Codex CLI in a Jupyter terminal, and GitHub Copilot's Codex-family chat models work in NBI's own chat through Copilot's Responses endpoint. Both are covered in [Coding-agent launchers, Codex, and a hardened platform]({% post_url 2026-05-28-coding-agent-launchers-and-beyond %}).

NBI 5.4 adds a third, and this one is a different kind of integration. In ACP mode, Codex itself is the agent behind the chat sidebar: it plans, reads and edits your workspace, and runs commands, while NBI renders the conversation, the tool calls, and the approval prompts. By default Codex asks before edits and before anything beyond trusted read-only commands. ACP mode is experimental and off by default, and its biggest limit is worth knowing up front: Codex works on your files and runs commands, but it cannot run cells in the notebook you have open. This post covers how to enable it, what a turn looks like, how approvals and Codex's sandbox fit together, and the rest of the current limits.

## ACP in brief

The [Agent Client Protocol](https://agentclientprotocol.com/) (ACP) standardizes how an application hosts a coding agent. The agent runs as a subprocess and talks JSON-RPC over stdio; the host sends prompts and renders what comes back, including streamed text, tool calls, and permission requests. The agent owns its model calls and its tool loop. The host owns the user interface.

In ACP mode, NBI is the host. Codex speaks ACP through the [`codex-acp`](https://github.com/zed-industries/codex-acp) adapter, which NBI launches with `npx` the first time it is needed, usually the first turn. Because the agent side is a protocol rather than an SDK, this is also the groundwork for other agents: Codex is the first agent type NBI registers, and the ACP tab's agent-type dropdown is where others would appear. For now, it is a dropdown of one.

## Turning it on

Two gates control ACP mode, an admin policy and a user checkbox, and both start off.

For administrators, `NBI_ACP_MODE_POLICY` (traitlet `acp_mode_policy`) governs whether the mode can be enabled at all. It defaults to `force-off`, which hides the ACP settings tab and clamps the setting off on every config write. That default is deliberate: an external agent that can edit files and run commands is something a deployment should opt into, not something a user stumbles onto. Set the policy to `user-choice` to make the mode available, or `force-on` to turn it on for everyone.

For users, the ACP tab in NBI Settings holds the rest. Check **Enable ACP mode**, and the chat sidebar switches over. ACP mode and Claude mode are mutually exclusive, so enabling one turns the other off. Unless you override the launch command (see below), the server needs `npx` on its `PATH` and access to the npm registry, because the first launch fetches a pinned version of the adapter. Expect that first start to take a little longer.

![The ACP tab in NBI Settings with ACP mode enabled, the full access option unavailable, Codex selected as the agent type, an optional chat model, and an API key field locked by the OPENAI_API_KEY environment variable](/assets/images/acp-codex/settings-acp-tab.png)

The tab also takes an optional chat model (leave it blank for the agent's default), an API key, and a base URL for routing through a gateway. These follow the same environment-variable locks as Claude mode: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `NBI_ACP_CHAT_MODEL` each pin and lock their field. `NBI_ACP_AGENT_COMMAND` overrides the command NBI uses to launch the adapter, for example to run a preinstalled adapter instead of fetching one with `npx`. NBI still appends its own Codex `-c` options to that command, which is how it applies the approval policy, so a replacement has to accept them.

## Signing Codex in

Codex can authenticate two ways, and NBI treats them differently.

With an API key, either in the ACP tab or in `OPENAI_API_KEY`, NBI runs Codex with its own `CODEX_HOME` under the NBI user directory. Codex's configuration then comes from a directory NBI controls, so neither the workspace's nor your personal `~/.codex` settings are read. This is the recommended setup for shared and locked-down deployments. One thing to plan for: Codex saves the key in that directory's `auth.json`, even when NBI only read it from the environment, so treat the NBI user directory as holding a credential.

Without a key, Codex relies on an existing ChatGPT sign-in for the user running the server, the kind `codex login` creates, read from that user's `~/.codex` (or `CODEX_HOME`, if set). The ACP tab has no sign-in button, and a remote or headless server has no browser to finish a new sign-in, so create the login first. This path is convenient on a personal machine, but your own Codex configuration, whatever you have put in it, then applies to the agent NBI hosts. NBI's approval-policy override still takes precedence; the rest of that configuration, including its sandbox setting, does not get overridden.

## A turn, start to finish

To see the whole loop, here is a small, real example: a script meant to total revenue by region, which instead sums unit counts and confidently prints them as dollars. The prompt is simply "Run analysis.py and check whether the revenue totals look right. Fix anything that's wrong."

Codex inspects the workspace, runs the script, reads the CSV to check the column names, and works out that the script is summing `units` rather than `units * unit_price`. Its tool calls appear as grouped cards, and the proposed edit renders as an inline diff. The edit does not land until you approve it.

![NBI chat sidebar in ACP mode: Codex explains that the script sums units instead of revenue, lists its tool calls, shows an inline diff changing units to units times unit price, and waits on an approval card for the edit](/assets/images/acp-codex/codex-edit-approval.png){: width="430" }

After approval, Codex applies the edit, reruns the script, and cross-checks the totals with an independent calculation, which is more skepticism than the original script ever showed. NBI's refresh-on-disk-change setting, on by default, updates the open editor without a manual reload.

![The finished turn in the NBI chat sidebar: the approved edit marked complete, the verification commands completed, and Codex confirming the fix with corrected totals of 665.38 for North, 608.27 for South, and 1,022.80 for West](/assets/images/acp-codex/codex-fix-result.png){: width="430" }

## Approvals, the sandbox, and full access

The approval cards are NBI's existing tool-call confirmation flow, reused for ACP. What decides when they appear is Codex's approval policy, and NBI pins that policy for you.

Unless full access is turned on, NBI starts the adapter with `-c approval_policy="untrusted"`, relying on Codex to honor that command-line override above its configuration file. Under it, Codex asks before edits and before anything beyond trusted read-only commands. In the example above, Codex asked before running the script and before the edit, while `git diff` ran without a prompt.

Approvals are only half of the picture. The other half is Codex's own sandbox. With an API key and NBI's isolated `CODEX_HOME`, Codex runs in a read-only sandbox with network access restricted, so a command that runs without asking, like that `git diff`, still cannot write anything. Approval is how an action gets past that sandbox: when you approve something the sandbox would block, such as the edit in the example, Codex carries it out anyway. Treat an approval as letting that action run with the access it needs.

That is also why full access deserves a careful read. Full access switches the pinned policy to `approval_policy="never"`, so Codex stops asking. It does not change the sandbox, and NBI leaves that to Codex's configuration. With the read-only sandbox of the API-key setup, an action that would have needed your approval is simply refused instead. Running the same example with full access on, Codex found the bug and computed the correct totals, but the read-only sandbox rejected its edit, so it handed back the fix for you to apply. `NBI_ACP_FULL_ACCESS_POLICY` (traitlet `acp_full_access_policy`) decides whether full access is on the table: at its default of `force-off` it stays off, `user-choice` makes the **Full access** checkbox in the ACP tab available, and `force-on` turns it on for every session.

It is worth being precise about what this gate is, and what it is not. As the approval card itself says, Codex decides which tools to ask about, so some actions may run without a prompt. NBI mediates the approvals Codex requests; it does not enforce a tool allowlist inside the agent the way its Claude tool policies do. The ACP tab states the related risk plainly: content the agent reads can steer what it runs. If those constraints do not fit a deployment, keep `NBI_ACP_MODE_POLICY` at `force-off`.

## Sessions

The sidebar header's history button lists earlier sessions from the current workspace, so you can pick up where you left off, and the new-session button starts over. Resuming goes through the agent's own `session/list` and `session/load`, so the history is Codex's rather than a copy NBI keeps. A resumed session picks up the conversation's context, and the sidebar marks it as resumed rather than redrawing the earlier messages.

## What it does not do yet

ACP mode is marked experimental for concrete reasons, and it is better to know them up front than halfway through a task.

- **No notebook UI tools.** In Claude mode the agent can create notebooks, insert and run cells in the live kernel, and drive the terminal through NBI's Jupyter UI tools. In ACP mode those tools are not yet available to the agent. Codex works on your files through its own tools, as in the example above, but it cannot run cells in the notebook you have open.
- **No NBI MCP servers.** MCP servers configured in NBI are not passed to Codex. The only NBI-provided server it receives supplies the workspace root.
- **One agent type.** Codex is the only registered agent today.
- **Approval scope.** As described above, NBI relays the approvals Codex asks for rather than enforcing its own allowlist, and what the agent can do without asking depends on Codex's sandbox.

For work that depends on driving the notebook itself, Claude mode remains the more complete agent mode.

## Try it

ACP mode ships in NBI 5.4:

```bash
pip install --upgrade notebook-intelligence
```

You also need Node.js on the machine running JupyterLab (for `npx`), plus either an `OPENAI_API_KEY` or an existing Codex ChatGPT sign-in for that user. Set `NBI_ACP_MODE_POLICY=user-choice` before starting JupyterLab, then enable ACP mode from the ACP tab in NBI Settings. If something is missing, the Status card at the top of Settings says which: a missing `npx` blocks the mode, and a missing key shows as a warning. The administrator controls and the known limitations are documented in [Gating the experimental ACP agent](https://github.com/plmbr/notebook-intelligence/blob/main/docs/admin-guide.md#gating-the-experimental-acp-agent-378), and the rest of the release is covered in the [NBI 5.4.0 release post]({% post_url 2026-09-11-v5-4-0 %}).
