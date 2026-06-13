from notebook_intelligence.message_sanitizer import sanitize_chat_history_tool_calls


def test_preserves_matched_assistant_tool_call_block():
    messages = [
        {"role": "user", "content": "run it"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q":"x"}'},
                }
            ],
            "ui_parts": [{"type": "tool-invocation"}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "done"},
    ]

    sanitized = sanitize_chat_history_tool_calls(messages)

    assert sanitized == [
        {"role": "user", "content": "run it"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q":"x"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "done"},
    ]


def test_drops_dangling_tool_calls_and_empty_assistant():
    messages = [
        {"role": "user", "content": "run it"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q":"x"}'},
                }
            ],
        },
        {"role": "user", "content": "next"},
    ]

    sanitized = sanitize_chat_history_tool_calls(messages)

    assert sanitized == [
        {"role": "user", "content": "run it"},
        {"role": "user", "content": "next"},
    ]


def test_drops_orphan_tool_message():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "call_1", "content": "orphan"},
        {"role": "assistant", "content": "done"},
    ]

    sanitized = sanitize_chat_history_tool_calls(messages)

    assert sanitized == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "done"},
    ]


def test_keeps_only_matched_tool_calls_and_matching_tool_results():
    messages = [
        {
            "role": "assistant",
            "content": "Let me try two things.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q":"a"}'},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q":"b"}'},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_2", "content": "matched"},
        {"role": "tool", "tool_call_id": "call_x", "content": "orphan"},
        {"role": "assistant", "content": "final"},
    ]

    sanitized = sanitize_chat_history_tool_calls(messages)

    assert sanitized == [
        {
            "role": "assistant",
            "content": "Let me try two things.",
            "tool_calls": [
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q":"b"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_2", "content": "matched"},
        {"role": "assistant", "content": "final"},
    ]


def test_removes_non_list_tool_calls_field():
    messages = [
        {"role": "assistant", "content": "hello", "tool_calls": {"id": "bad"}},
    ]

    sanitized = sanitize_chat_history_tool_calls(messages)

    assert sanitized == [
        {"role": "assistant", "content": "hello"},
    ]
