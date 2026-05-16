---
layout: home
title: Notebook Intelligence
description: A JupyterLab extension for Claude Code, GitHub Copilot, Ollama, and OpenAI-compatible models — with MCP, Skills, Plugins, and admin policy.
---

<section class="hero">
  <div class="container two-col">
    <div>
      <p class="hero__eyebrow">JupyterLab extension</p>
      <h1 class="hero__headline">Claude Code, in your notebook.</h1>
      <p class="hero__sub">
        A JupyterLab extension built for agentic AI — first-class Claude Code, with
        GitHub Copilot, Ollama, and OpenAI-compatible models as drop-in alternates.
        Skills, Plugins, MCP, and admin policy included.
      </p>
      <div class="hero__cta">
        <a class="btn btn--primary" href="#install">Install</a>
        <a class="btn btn--ghost" href="https://github.com/notebook-intelligence/notebook-intelligence" rel="noopener">View on GitHub</a>
      </div>
    </div>
    <div>
      <figure class="hero__media">
        <img src="{{ '/assets/images/hero/nbi-claude-chat.png' | relative_url }}"
             alt="JupyterLab with the Notebook Intelligence chat sidebar open, mid-conversation with Claude Code."
             width="1200" height="800" loading="eager" fetchpriority="high">
      </figure>
    </div>
  </div>
</section>

<section class="providers">
  <div class="container">
    <p class="providers__label">Works with</p>
    <div class="providers__row" aria-label="Supported model providers">
      <span>Claude&nbsp;Code</span>
      <span>GitHub&nbsp;Copilot</span>
      <span>Ollama</span>
      <span>OpenAI</span>
      <span>vLLM</span>
      <span>LiteLLM</span>
    </div>
  </div>
</section>

<section class="stripe" id="claude">
  <div class="container stripe__grid">
    <div>
      <p class="stripe__eyebrow">Claude Code, first</p>
      <h2 class="stripe__title">Sessions, Skills, Plugins, and MCP — all from JupyterLab.</h2>
      <p class="stripe__body">
        Run Claude Code as a first-class provider for chat, agent runs, and notebook editing.
        Resume any transcript from the launcher. Manage Skills and Plugins from the UI.
        Agent mode edits, runs, and fixes cells without leaving the notebook.
      </p>
      <a class="stripe__link" href="{{ '/features/claude-code/' | relative_url }}">Read more →</a>
    </div>
    <figure class="stripe__media">
      <img src="{{ '/assets/images/features/claude-launcher.png' | relative_url }}"
           alt="JupyterLab launcher showing a Claude Code tile with session picker."
           width="1200" height="800" loading="lazy">
    </figure>
  </div>
</section>

<section class="stripe stripe--reverse">
  <div class="container stripe__grid">
    <div>
      <p class="stripe__eyebrow">Bring any other model</p>
      <h2 class="stripe__title">GitHub Copilot, Ollama, OpenAI-compatible — same chat surface.</h2>
      <p class="stripe__body">
        Sign in to Copilot once and use any of its chat or completion models. Point Ollama
        at a local model you already pulled. Wire NBI to any OpenAI- or LiteLLM-compatible
        endpoint with a base URL, model ID, and key.
      </p>
      <a class="stripe__link" href="{{ '/providers/' | relative_url }}">Compare providers →</a>
    </div>
    <div class="stripe__media" style="padding: var(--space-5);">
{% highlight json %}
{
  "chat_model": {
    "provider": "openai-compatible",
    "model": "gpt-oss-120b",
    "base_url": "https://gateway.internal/v1",
    "api_key": "sk-..."
  },
  "inline_completion_model": {
    "provider": "ollama",
    "model": "qwen2.5-coder:7b"
  }
}
{% endhighlight %}
    </div>
  </div>
</section>

<section class="stripe">
  <div class="container stripe__grid">
    <div>
      <p class="stripe__eyebrow">Extend it</p>
      <h2 class="stripe__title">MCP servers, Claude Skills, and Plugins — managed from the lab.</h2>
      <p class="stripe__body">
        Expose your own tools, databases, and APIs over the Model Context Protocol.
        Author Skills inline or import from GitHub. Sync an org-wide manifest so every
        user in the lab lands with the same set.
      </p>
      <a class="stripe__link" href="{{ '/features/skills-plugins/' | relative_url }}">Skills, Plugins, MCP →</a>
    </div>
    <figure class="stripe__media">
      <img src="{{ '/assets/images/features/skills-panel.png' | relative_url }}"
           alt="Skills management panel inside the JupyterLab Settings dialog."
           width="1200" height="800" loading="lazy">
    </figure>
  </div>
</section>

<section class="stripe stripe--reverse">
  <div class="container stripe__grid">
    <div>
      <p class="stripe__eyebrow">For administrators</p>
      <h2 class="stripe__title">Pin the provider. Lock the endpoint. Ship to your team.</h2>
      <p class="stripe__body">
        Environment-variable policies set the provider, model, and endpoints — useful for
        managed JupyterHub deployments. Each policy is a force-on / force-off / user-choice
        triad, surfaced in Settings as a locked control. Org-managed Skills sync from a
        manifest you control.
      </p>
      <a class="stripe__link" href="{{ '/admin/' | relative_url }}">Admin and policy →</a>
    </div>
    <div class="stripe__media" style="padding: var(--space-5);">
{% highlight bash %}
# Pin the Claude provider and a specific model.
export NBI_CHAT_MODEL_PROVIDER=anthropic
export NBI_CLAUDE_CHAT_MODEL=claude-sonnet-4-6

# Force-on Claude mode; users can't turn it off.
export NBI_CLAUDE_MODE_POLICY=force-on

# Disable user-driven GitHub Skill imports
# (org manifest still works).
export NBI_ALLOW_GITHUB_SKILL_IMPORT=false
{% endhighlight %}
    </div>
  </div>
</section>

<section class="section" id="install">
  <div class="container-narrow">
    <p class="eyebrow">First run</p>
    <h2>Install and try it in five minutes.</h2>
    <p class="lede">
      NBI installs into any JupyterLab 4 environment. Restart the lab and the
      chat sidebar appears on the left.
    </p>

    <p>
      <span class="install-pill">
        <span class="install-pill__prompt" aria-hidden="true">$</span>
        <span class="install-pill__cmd" id="install-cmd">pip install notebook-intelligence</span>
        <button class="install-pill__copy" type="button" data-copy="#install-cmd" aria-label="Copy install command">
          {% include copy-icon.html %}
        </button>
      </span>
    </p>

    <ol class="steps">
      <li><strong>Install.</strong> <code>pip install notebook-intelligence</code> into the same env as your JupyterLab.</li>
      <li><strong>Restart JupyterLab.</strong> The NBI sidebar appears on the left.</li>
      <li><strong>Pick a provider.</strong> Open Settings → NBI and configure Claude Code, Copilot, Ollama, or an OpenAI-compatible endpoint.</li>
      <li><strong>Send your first prompt.</strong> Or hit <kbd>Cmd</kbd>+<kbd>I</kbd> inside a code cell for inline chat.</li>
    </ol>

    <p style="margin-top: var(--space-8);">
      <a class="btn btn--ghost" href="{{ '/install/' | relative_url }}">Full install guide →</a>
    </p>
  </div>
</section>
