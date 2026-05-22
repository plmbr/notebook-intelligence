"""Regression tests for the Claude Code chat participant's system
prompt (`build_claude_system_prompt` in `notebook_intelligence/claude.py`).

The prompt is the only knob we have to steer the agent's bias toward
"create a notebook to answer this" vs. "reply in chat" without
disabling the Jupyter UI tools entirely. Issue #335 documented the
former case (attach a file, ask "summarize this", agent creates a
notebook to hold the summary). The fix is a paragraph in the prompt
telling the agent to default to chat replies and only create
artifacts on explicit request.

These tests pin the load-bearing phrases of that paragraph so a
future "tighten the prompt" rewrite can't silently drop the guard.
"""

from notebook_intelligence.claude import (
    JUPYTER_UI_TOOLS_SYSTEM_PROMPT,
    build_claude_system_prompt,
)


class TestBuildClaudeSystemPrompt:
    def test_includes_default_to_chat_reply_guidance(self):
        """The 'default to chat' paragraph is the load-bearing fix for
        issue #335; dropping it silently regresses the
        attach-and-ask-question flow back to the notebook-creation
        bias."""
        prompt = build_claude_system_prompt(
            jupyter_ui_tools_enabled=True,
            jupyter_root_dir="/workspace",
        )
        assert "Default to answering questions directly in your chat reply" in prompt
        assert (
            "Do not create a notebook, file, or other workspace artifact "
            "unless the user explicitly asks for one"
        ) in prompt

    def test_includes_attached_file_question_carveout(self):
        """The specific example from issue #335 (attach a file, ask a
        question, agent creates a notebook) is called out so a future
        prompt rewrite can't drop the most common manifestation of
        the bias."""
        prompt = build_claude_system_prompt(
            jupyter_ui_tools_enabled=True,
            jupyter_root_dir="/workspace",
        )
        assert "When the user attaches a file and asks a question" in prompt
        assert "do not produce a new notebook to hold the answer" in prompt

    def test_includes_jupyter_ui_tools_prompt_when_enabled(self):
        prompt = build_claude_system_prompt(
            jupyter_ui_tools_enabled=True,
            jupyter_root_dir="/workspace",
        )
        assert JUPYTER_UI_TOOLS_SYSTEM_PROMPT.strip() in prompt

    def test_excludes_jupyter_ui_tools_prompt_when_disabled(self):
        prompt = build_claude_system_prompt(
            jupyter_ui_tools_enabled=False,
            jupyter_root_dir="/workspace",
        )
        # Pick a distinctive phrase that only appears in the tools
        # prompt, so a future rephrase of the surrounding prose can't
        # accidentally pass this assertion.
        assert "nbi' MCP server" not in prompt

    def test_default_to_chat_guidance_persists_without_ui_tools(self):
        """The chat-default bias guard must apply regardless of
        whether the UI-tools section is included — the agent can
        still produce notebooks via the built-in `Write` tool, and
        issue #335's mechanism (over-eager artifact creation) is
        independent of the NBI MCP toolset."""
        prompt = build_claude_system_prompt(
            jupyter_ui_tools_enabled=False,
            jupyter_root_dir="/workspace",
        )
        assert "Default to answering questions directly in your chat reply" in prompt

    def test_chat_default_guidance_precedes_jupyter_ui_tools_block(self):
        """The UI-tools block ends with "If the user has asked you to
        create a notebook, save it...", which a model with strong
        recency bias could read as permission. Pin that the
        chat-default paragraph sits BEFORE the UI-tools block so the
        last word the model sees on the create-or-not question is the
        guard, not the conditional-save instruction."""
        prompt = build_claude_system_prompt(
            jupyter_ui_tools_enabled=True,
            jupyter_root_dir="/workspace",
        )
        guard_position = prompt.index("Default to answering questions")
        tools_position = prompt.index("nbi' MCP server")
        assert guard_position < tools_position

    def test_pins_explicit_request_examples(self):
        """The explicit-request examples are as load-bearing as the
        prohibition: they tell the model WHICH user prompts DO call
        for artifact creation. Without these the guard could be
        rewritten into a blanket "never create" that breaks legitimate
        "write me a notebook" requests."""
        prompt = build_claude_system_prompt(
            jupyter_ui_tools_enabled=True,
            jupyter_root_dir="/workspace",
        )
        assert '"create a notebook that..."' in prompt
        assert '"write me a script to..."' in prompt
        assert '"save this as a file"' in prompt
        # "show me a notebook that..." disambiguates the "show me"
        # verb (which also appears in the question-style example
        # list); pin it so a future edit can't collapse the two
        # surfaces and reintroduce the bias.
        assert '"show me a notebook that..."' in prompt

    def test_interpolates_jupyter_root_dir(self):
        prompt = build_claude_system_prompt(
            jupyter_ui_tools_enabled=True,
            jupyter_root_dir="/home/user/proj",
        )
        assert "'/home/user/proj'" in prompt
