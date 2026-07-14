import asyncio
from unittest.mock import Mock, AsyncMock
from notebook_intelligence.base_chat_participant import BaseChatParticipant
from notebook_intelligence.base_chat_participant import CreateNewNotebookTool
from notebook_intelligence.base_chat_participant import ListAvailableNotebookKernelsTool
from notebook_intelligence.api import ChatRequest, ChatResponse, ChatMode, CancelToken
from notebook_intelligence.ruleset import RuleContext
from notebook_intelligence.rule_injector import RuleInjector


class TestBaseChatParticipantIntegration:
    def test_init_with_default_rule_injector(self):
        """Test BaseChatParticipant initialization with default rule injector."""
        participant = BaseChatParticipant()
        
        assert participant._rule_injector is not None
        assert isinstance(participant._rule_injector, RuleInjector)
    
    def test_init_with_custom_rule_injector(self):
        """Test BaseChatParticipant initialization with custom rule injector."""
        mock_injector = Mock(spec=RuleInjector)
        participant = BaseChatParticipant(rule_injector=mock_injector)
        
        assert participant._rule_injector is mock_injector
    
    def test_inject_rules_into_system_prompt(self):
        """Test rule injection into system prompt."""
        mock_injector = Mock(spec=RuleInjector)
        mock_injector.inject_rules.return_value = "Enhanced prompt with rules"
        
        participant = BaseChatParticipant(rule_injector=mock_injector)
        request = Mock(spec=ChatRequest)
        
        base_prompt = "You are a helpful assistant."
        result = participant._inject_rules_into_system_prompt(base_prompt, request)
        
        assert result == "Enhanced prompt with rules"
        mock_injector.inject_rules.assert_called_once_with(base_prompt, request)
    
    def test_handle_ask_mode_chat_request_with_rules(self):
        """Test ask mode chat request handling with rule injection."""
        mock_injector = Mock(spec=RuleInjector)
        mock_injector.inject_rules.return_value = "Enhanced system prompt"

        participant = BaseChatParticipant(rule_injector=mock_injector)

        # Mock the chat model and host
        mock_chat_model = Mock()
        mock_chat_model.provider.name = "test-provider"
        mock_chat_model.provider.id = "test-provider"
        mock_chat_model.name = "test-model"
        mock_chat_model.completions = Mock()

        mock_host = Mock()
        mock_host.chat_model = mock_chat_model

        # Create request with rule context
        rule_context = RuleContext(
            filename="test.ipynb",
            language="python",
            kernel_name="python3",
            mode="ask"
        )

        request = ChatRequest(
            host=mock_host,
            chat_mode=ChatMode("ask", "Ask"),
            prompt="Test prompt",
            chat_history=[],
            cancel_token=Mock(spec=CancelToken),
            rule_context=rule_context
        )

        response = Mock(spec=ChatResponse)
        response.stream = Mock()

        # Call the method
        asyncio.run(participant.handle_ask_mode_chat_request(request, response))

        # Verify rule injection was called
        mock_injector.inject_rules.assert_called_once()

        # Verify chat model was called with enhanced prompt
        mock_chat_model.completions.assert_called_once()
        call_args = mock_chat_model.completions.call_args[0]
        messages = call_args[0]

        # Check that the system message contains the enhanced prompt
        assert len(messages) >= 1
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Enhanced system prompt"

    def test_handle_chat_request_agent_mode_with_rules(self):
        """Test agent mode chat request handling with rule injection."""
        mock_injector = Mock(spec=RuleInjector)
        mock_injector.inject_rules.return_value = "Enhanced agent prompt"
        
        participant = BaseChatParticipant(rule_injector=mock_injector)
        
        # Mock the host and dependencies
        mock_host = Mock()
        mock_host.chat_model = Mock()
        mock_host.get_extension_toolset.return_value = None
        mock_host.get_mcp_server.return_value = None
        
        # Create request for agent mode
        rule_context = RuleContext(
            filename="test.py",
            language="python",
            kernel_name="python3",
            mode="agent"
        )
        
        from notebook_intelligence.api import RequestToolSelection
        tool_selection = RequestToolSelection(
            built_in_toolsets=[],
            mcp_server_tools={},
            extension_tools={}
        )
        
        request = ChatRequest(
            host=mock_host,
            chat_mode=ChatMode("agent", "Agent"),
            tool_selection=tool_selection,
            prompt="Test agent prompt",
            chat_history=[],
            cancel_token=Mock(spec=CancelToken),
            rule_context=rule_context
        )
        
        response = Mock(spec=ChatResponse)
        
        # Mock the handle_chat_request_with_tools method
        participant.handle_chat_request_with_tools = AsyncMock()
        
        # Call the method
        asyncio.run(participant.handle_chat_request(request, response))
        
        # Verify rule injection was called
        mock_injector.inject_rules.assert_called_once()
        
        # Verify handle_chat_request_with_tools was called with enhanced system prompt
        participant.handle_chat_request_with_tools.assert_called_once()
        call_args = participant.handle_chat_request_with_tools.call_args
        
        # The call should be handle_chat_request_with_tools(request, response, options)
        # So call_args[0] is positional args, call_args[1] is keyword args
        if len(call_args) > 1 and 'options' in call_args[1]:
            options = call_args[1]['options']
        else:
            # Options might be passed as positional argument
            options = call_args[0][2] if len(call_args[0]) > 2 else {}
        
        assert "system_prompt" in options
        assert options["system_prompt"] == "Enhanced agent prompt"

    def test_handle_ask_mode_new_notebook_uses_request_language_and_kernel(self):
        participant = BaseChatParticipant()

        mock_chat_model = Mock()
        mock_host = Mock()
        mock_host.chat_model = mock_chat_model

        request = ChatRequest(
            host=mock_host,
            chat_mode=ChatMode("ask", "Ask"),
            command="newNotebook",
            prompt="Create a notebook in lang-x",
            language="lang-x",
            kernel_name="kernel-x",
            chat_history=[{"role": "user", "content": "Create a notebook in lang-x"}],
            cancel_token=Mock(spec=CancelToken),
            rule_context=RuleContext(
                filename="test.ipynb",
                language="lang-x",
                kernel_name="kernel-x",
                mode="ask"
            )
        )

        response = Mock(spec=ChatResponse)
        response.run_ui_command = AsyncMock(
            side_effect=[
                {"path": "Untitled.ipynb"},
                {"ok": True},
                {"ok": True},
            ]
        )
        response.stream = Mock()
        response.finish = Mock()

        participant.generate_code_cell = AsyncMock(return_value='emit("hi")')
        participant.generate_markdown_for_code = AsyncMock(return_value="# Lang X")

        asyncio.run(participant.handle_ask_mode_chat_request(request, response))

        first_call = response.run_ui_command.await_args_list[0]
        assert first_call.args == (
            'notebook-intelligence:create-new-notebook',
            {'code': '', 'language': 'lang-x', 'kernelName': 'kernel-x'}
        )

    def test_list_available_notebook_kernels_tool_reads_frontend_environment(self):
        tool = ListAvailableNotebookKernelsTool()
        request = ChatRequest()
        response = Mock(spec=ChatResponse)
        response.run_ui_command = AsyncMock(
            return_value={
                "kernels": [
                    {
                        "language": "lang-a",
                        "kernelName": "kernel-a",
                        "displayName": "Kernel A",
                    },
                    {
                        "language": "lang-b",
                        "kernelName": "kernel-b",
                        "displayName": "Kernel B",
                    },
                ]
            }
        )

        result = asyncio.run(tool.handle_tool_call(request, response, {}, {}))

        response.run_ui_command.assert_awaited_once_with(
            "notebook-intelligence:list-available-notebook-kernels",
            {},
        )
        assert '"kernelName": "kernel-a"' in result
        assert '"kernelName": "kernel-b"' in result

    def test_get_tool_by_name_returns_kernel_listing_tool(self):
        tool = BaseChatParticipant.get_tool_by_name("list_available_notebook_kernels")
        assert isinstance(tool, ListAvailableNotebookKernelsTool)
