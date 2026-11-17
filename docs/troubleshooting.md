# Troubleshooting

Common problems with copy-pasteable fixes. If your problem isn't listed, open an issue with the information requested in [CONTRIBUTING.md](../CONTRIBUTING.md#filing-a-good-bug-report).

## "Extension installed but I don't see anything in JupyterLab"

After `pip install notebook-intelligence`, restart JupyterLab. If a restart doesn't help, verify both halves of the extension are enabled:

```bash
jupyter server extension list   # look for "notebook_intelligence  enabled"
jupyter labextension list       # look for "@plmbr/notebook-intelligence ... enabled"
```

If either is disabled or missing:

```bash
jupyter server extension enable notebook_intelligence
pip install --force-reinstall notebook-intelligence   # if the labextension is missing
```

The chat sidebar appears as a left-rail icon in the JupyterLab UI. Click it to open the panel.

## "Two Notebook Intelligence icons in the sidebar"

Seeing two NBI sidebar tabs with the same sparkle icon means two copies of the labextension are loaded at once. This happens after upgrading across the package rename: the labextension was renamed from `@notebook-intelligence/notebook-intelligence` to `@plmbr/notebook-intelligence` in the 5.0 line, and an upgrade installs the new one but can leave the old one behind. JupyterLab then loads both, and each registers its own sidebar tab.

Confirm it:

```bash
jupyter labextension list
```

If both `@notebook-intelligence/notebook-intelligence` and `@plmbr/notebook-intelligence` are listed as enabled, the first is the stale duplicate. Remove its directory (its path is shown in the list), checking both your environment prefix and the per-user location:

```bash
rm -rf <prefix>/share/jupyter/labextensions/@notebook-intelligence
rm -rf ~/.local/share/jupyter/labextensions/@notebook-intelligence
```

Restart JupyterLab and hard-refresh the browser; only `@plmbr/notebook-intelligence` should remain. If you would rather not delete files, `jupyter labextension disable @notebook-intelligence/notebook-intelligence` stops JupyterLab from loading the old extension reversibly. Note that `pip uninstall` does not remove the stale directory on its own, because the old labextension is no longer tracked by the current package.

## "GitHub login window doesn't open" or Copilot login does nothing

NBI uses GitHub's device-flow login. The server extension prints the URL and one-time code to the JupyterLab terminal. Look there first.

If your browser blocks the popup, copy the URL from the terminal output and paste it into a new tab.

If the device-flow request itself fails (timeout, network error), check that your network allows outbound HTTPS to `github.com` and `api.githubcopilot.com`. See [`PRIVACY.md`](../PRIVACY.md#egress-allowlist) for the full egress list.

## "It says 'no models available'"

NBI started successfully but the configured provider returned an empty model list. Check, in order:

1. **Provider auth** — open the NBI Settings dialog. For GitHub Copilot, sign in. For OpenAI-compatible or LiteLLM-compatible, paste an API key. For Ollama, ensure the daemon is running locally. For Claude mode, paste an Anthropic API key in the Claude tab.
2. **Custom Base URL** — if you set one, confirm it points at the provider's chat-completions endpoint and that it's reachable from the JupyterLab process.
3. **Provider gating** — if your admin disabled the provider via `disabled_providers`, the dropdown won't list its models. See [`admin-guide.md`](admin-guide.md#restricting-features-for-managed-deployments).
4. **Model refresh** — for Claude, click the refresh button in the Claude settings panel.

## "I'm getting a 401"

A 401 from the LLM provider almost always means an expired or invalid API key.

- **GitHub Copilot** — sign out and sign in again from NBI Settings → GitHub Copilot.
- **OpenAI-compatible, LiteLLM-compatible, or Claude** — paste a fresh key in NBI Settings under the respective provider.
- **Stored Copilot token corrupted** — delete `~/.jupyter/nbi/user-data.json` and sign in again.

A 401 from a managed-skills manifest fetch means `NBI_MANAGED_SKILLS_TOKEN` is missing or expired. The reconciler logs the failure and leaves installed managed skills in place.

## Claude mode does nothing or hangs on "Thinking…"

Claude mode requires the [Claude Code CLI](https://code.claude.com/) on the user's `PATH`. If the CLI is missing or fails to start, the chat sidebar hangs.

```bash
which claude   # should print a path
claude --version
```

If `claude` is installed in a non-default location, set the `NBI_CLAUDE_CLI_PATH` environment variable to its absolute path before starting JupyterLab.

If Claude mode worked previously but is now stuck, check the JupyterLab terminal for `claude-agent-sdk` errors. A failed-to-start agent thread is the usual culprit; restart JupyterLab to retry.

## MCP server crashes or tools missing in `@mcp`

MCP stdio servers run as subprocesses of the user's Jupyter Server. If a server crashes at startup:

1. Check the JupyterLab terminal for the server's stderr output.
2. Verify the `command` and `args` in `~/.jupyter/nbi/mcp.json` are correct and the binary is on `PATH`.
3. For `npx -y` servers, confirm Node.js is installed (`node --version`).
4. Use the **Reload MCP servers** action from NBI Settings → MCP after fixing the config — this re-runs discovery without restarting JupyterLab.

If the configured command is not an MCP server at all, it never answers the MCP handshake. NBI gives up on it after 60 seconds (`NBI_MCP_CONNECT_TIMEOUT`), marks the server failed, and logs that the command may not be an MCP server. A command that writes non-JSON output in a loop would otherwise fill the log with one parse error per line, so those records are capped at a few per 10 seconds and the number withheld is reported with the failure.

If the LLM is connected but tools aren't being called, confirm the model supports tool calling. All GitHub Copilot models do; for other providers, check the provider's docs.

## Where do logs live, and how do I turn on debug?

NBI does not have a separate log file. Server-side messages go to **stderr of the JupyterLab process** — the terminal where you ran `jupyter lab`.

To see more detail:

```bash
jupyter lab --debug
```

`NBI_LOG_LEVEL=DEBUG` is another option, but it is not limited to NBI: it sets the level of Python's root logger, so every library that logs through it (HTTP clients, model SDKs, MCP) logs at that level too, and model SDKs' debug output can include the prompts and messages they send. If something configured the root logger before NBI loaded, the variable has no effect.

Frontend errors go to the **browser DevTools console** (`Cmd+Option+I` on macOS, `Ctrl+Shift+I` on Linux or Windows). Look for messages from `notebook-intelligence`.

For configuration inspection:

```bash
cat ~/.jupyter/nbi/config.json
cat ~/.jupyter/nbi/mcp.json
ls ~/.jupyter/nbi/rules/         # ruleset files
ls ~/.claude/skills/             # Claude skills
ls ~/.claude/projects/           # Claude session transcripts
```

If `CLAUDE_CONFIG_DIR` is set, the Claude CLI keeps its skills and session transcripts under `$CLAUDE_CONFIG_DIR` instead of `~/.claude`, and NBI reads from the same place.

> Do not share the contents of `~/.jupyter/nbi/config.json` or `~/.jupyter/nbi/user-data.json` — they contain API keys or your encrypted GitHub token.

## "Skills reloaded" banner keeps appearing

NBI reloads the Claude SDK session whenever a skill changes on disk. If a script or editor frequently rewrites files under `~/.claude/skills/` (autoformatter, sync tool), it triggers the banner. Pause the writer or move the skill out of `~/.claude/skills/` while editing.

## "My shell command output shows `<redacted>`"

The agent's shell-execute tools (`execute_command` and the embedded terminal) automatically redact values for env vars whose name matches sensitive substrings (`TOKEN`, `SECRET`, `API_KEY`, `PASSWORD`, `OAUTH`, `BEARER`, `COOKIE`, `JWT`, `ACCESS_KEY`, …) plus tokens with well-known credential prefixes (`ghp_`, `sk-ant-`, `xoxb-`, `AKIA`, …). This prevents a verbose command like `env`, `printenv`, or `git` with credential-helper tracing from pasting your `GITHUB_TOKEN` / `ANTHROPIC_API_KEY` into chat history.

If you're debugging a credential helper and need the raw value, set `NBI_DISABLE_OUTPUT_SCRUB=1` in the JupyterLab process env and restart. Keep it off in normal use; the redaction is the only line of defense between an LLM-driven command and your secrets going to the model provider.

## The model loses track of earlier messages in a long chat

Ask-mode requests are fitted to 80% of the active model's context window, so a long conversation is pruned rather than sent whole and rejected. Complete prior turns are dropped oldest-first; the system prompt, your workspace rules, any inline-edit source, and your newest message are kept. When something is dropped the reply carries a short context note saying so, so an unexplained gap in the model's memory is usually a different problem.

Pruning only happens when NBI knows the window. GitHub Copilot models report theirs through the models API. **OpenAI-compatible and LiteLLM-compatible providers do not**, so NBI uses whatever **Context window** you set on the model in Settings, and if you leave it blank it passes history through untouched rather than pruning against a guessed number. If a self-hosted or gateway-fronted model starts failing on context length in long chats, setting that value is the fix.

Agent-mode tool loops are not budgeted; this applies to ask mode and the built-in generation commands.

## Tab indents instead of accepting a suggestion

Tab accepts an inline suggestion only while one is actually on screen; otherwise it indents, which is what Tab does everywhere else in a notebook. Earlier releases bound accept whenever the completer was active, so Tab could be swallowed in a cell with nothing to accept. If suggestions never appear at all, that is a different problem: see the two entries below.

## Settings says "Ready" but every chat turn fails

An OpenAI-compatible or LiteLLM-compatible provider needs an explicit **Model**. A blank field used to persist as an empty string, and the readiness card answered "Ready. Nothing needs configuring" while every turn went out with no model name and failed at the provider. Readiness now reports a blank required field as a blocking row naming the field. On an older release, check Settings for an empty Model box.

## A file changed on disk but the open tab did not reload

Two deliberate limits. A revert is skipped while that document's kernel is busy, so an agent edit made during a long-running cell appears when the cell finishes rather than mid-execution. And the reload notice is only shown for the document you are looking at, so files reverted in background tabs change without a message. Neither is an error; nothing is logged.

## Inline completion is too aggressive or too quiet

Tune the debounce delay in NBI Settings → Inline completion. Lower delays mean more requests, which means higher cost on paid providers. The default balances responsiveness against cost.

## Claude auto-complete suggests nothing

Claude mode signs in through the Claude CLI, which accepts a subscription login. Auto-complete does not go through the CLI: it calls the Anthropic API directly, so it needs a credential of its own. When none is visible to the Jupyter server, NBI leaves Claude auto-complete off and logs one warning per server run rather than failing on every pause in your typing.

Either give the server a credential or point auto-complete elsewhere:

- Add an **API key** under NBI Settings → Claude. This takes effect on save; no restart is needed.
- Or set `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) in the JupyterLab process environment. A process environment is fixed at launch, so export it **before** starting JupyterLab; exporting it in another shell afterwards has no effect. On current Anthropic SDK releases an `ANTHROPIC_PROFILE` or config-dir profile, the workload-identity variables, and a credential passed through `ANTHROPIC_CUSTOM_HEADERS` count as well. A variable set to an empty or whitespace value does not count, which is worth checking if your deployment writes `ANTHROPIC_API_KEY=` into an env file.
- Or set **Auto-complete model** to **None** to leave the feature off, or to **Inherit from general settings** to have your general inline-completion provider serve suggestions instead.

If your administrator pins the auto-complete model, that dropdown is disabled and the only remedy is giving the server a credential.

A misconfigured credential is a different case: an `ANTHROPIC_PROFILE` or `ANTHROPIC_CONFIG_DIR` pointing at files the Anthropic SDK cannot read logs `Could not create the Claude inline completion model` with the underlying error instead of the warning above. Fix the profile path rather than adding a key.

## NBI stays in English after choosing another language

NBI is translated only when JupyterLab's language pack for exactly that locale is installed in the Jupyter server's environment (for example `pip install jupyterlab-language-pack-fr-FR`) and JupyterLab was restarted afterwards. If JupyterLab's own menus are still in English, the pack is missing; if they are translated but NBI is not, hard-refresh the browser. A string with no translation yet appears in English, and logs and text sent to the model always stay English.

Replies from the model stay in English until **NBI Settings → General → Language → Reply in my JupyterLab language** is on. In Claude and ACP mode, a conversation keeps replying in that language after the setting is turned off, until you start a new chat. See [`translating.md`](translating.md).

## ACP mode: "Adapter runtime" is blocked

Since 6.3.0, NBI no longer downloads the ACP adapter with `npx`. The readiness card in NBI Settings, General shows **Adapter runtime** as blocked when it cannot find a preinstalled `codex-acp` on an absolute server `PATH` directory outside the workspace, or when `NBI_ACP_AGENT_COMMAND` does not start with the absolute path of an executable (for example a relative command, a bare `npx`, or an empty value). Readiness does not check that an absolute override is the adapter itself, so point it at the installed `codex-acp`, never at `npx`, another package runner, or an `env` wrapper. To fix a blocked check, install `@zed-industries/codex-acp@0.16.0` in a trusted location outside the workspace and put its executable's directory on the Jupyter server's `PATH`, or set `NBI_ACP_AGENT_COMMAND` to its absolute path. The Node.js it runs on must be on that `PATH` too. Then restart JupyterLab. To return to default discovery, unset `NBI_ACP_AGENT_COMMAND`; setting it to an empty value is an error. See [Gating the experimental ACP agent](admin-guide.md#gating-the-experimental-acp-agent-378).

## Still stuck?

- Check [GitHub issues](https://github.com/plmbr/notebook-intelligence/issues) for similar reports.
- Open a new issue including the information listed in [CONTRIBUTING.md](../CONTRIBUTING.md#filing-a-good-bug-report).
