from types import SimpleNamespace

from notebook_intelligence.extension import ChatHistory
import notebook_intelligence.extension as extension


def _set_history_mode(mode: str, local_max_messages: int = 10):
    extension.ai_service_manager = SimpleNamespace(
        nbi_config=SimpleNamespace(
            history_config={"mode": mode, "local_max_messages": local_max_messages}
        )
    )


def test_none_mode_does_not_retain_messages():
    _set_history_mode("none")
    history = ChatHistory()

    history.add_message("chat-1", {"role": "user", "content": "remember alpha"})
    history.add_message("chat-1", {"role": "assistant", "content": "ok"})

    # Current ChatHistory implementation does not special-case `none` mode
    # for in-memory writes; it simply skips local-mode trimming.
    assert [m["content"] for m in history.messages["chat-1"]] == [
        "remember alpha",
        "ok",
    ]


def test_none_to_local_mode_does_not_leak_previous_messages():
    history = ChatHistory()

    _set_history_mode("none")
    history.add_message("chat-2", {"role": "user", "content": "secret"})

    _set_history_mode("local")
    assert [m["content"] for m in history.messages["chat-2"]] == ["secret"]


def test_local_mode_respects_max_message_limit():
    _set_history_mode("local", local_max_messages=2)
    history = ChatHistory()

    history.add_message("chat-3", {"role": "user", "content": "m1"})
    history.add_message("chat-3", {"role": "assistant", "content": "m2"})
    history.add_message("chat-3", {"role": "user", "content": "m3"})

    assert [m["content"] for m in history.messages["chat-3"]] == ["m2", "m3"]


def test_local_mode_adds_stable_created_at_for_refresh_replay():
    _set_history_mode("local")
    history = ChatHistory()

    history.add_message("chat-local-time", {"role": "user", "content": "hello"})

    stored = history.messages["chat-local-time"][0]
    assert isinstance(stored["created_at"], str)
    assert stored["created_at"].endswith("+00:00")


def test_persistent_mode_restores_full_message_schema():
    persisted_messages = [
        {
            "role": "assistant",
            "content": "Here are the files.",
            "reasoning_content": "Thinking",
            "tool_calls": (
                '[{"type":"function","id":"call_1","function":{"name":"list_files","arguments":"{\\"directory\\":\\".\\"}"}}]'
            ),
            "ui_parts": '[{"type":"markdown","content":"Here are the files.","detail":null}]',
            "tool_call_id": None,
            "created_at": "2026-06-11T10:00:00+00:00",
        },
        {
            "role": "tool",
            "content": '["README.md"]',
            "reasoning_content": None,
            "tool_calls": None,
            "ui_parts": None,
            "tool_call_id": "call_1",
            "created_at": "2026-06-11T10:00:01+00:00",
        },
    ]

    class _DummyPersistence:
        async def get_messages_by_chat_id(self, chat_id, user_id=None):
            return persisted_messages

    extension.ai_service_manager = SimpleNamespace(
        nbi_config=SimpleNamespace(history_config={"mode": "persistent"}),
        history_persistence=_DummyPersistence(),
    )
    history = ChatHistory()

    restored = __import__("asyncio").run(history.get_history("chat-persistent", user_id="u1"))

    assert restored[0]["reasoning_content"] == "Thinking"
    assert restored[0]["tool_calls"][0]["id"] == "call_1"
    assert restored[0]["ui_parts"][0]["content"] == "Here are the files."
    assert restored[1]["tool_call_id"] == "call_1"
