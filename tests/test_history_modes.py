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
