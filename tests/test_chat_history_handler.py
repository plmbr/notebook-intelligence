import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

from jupyter_server.base.handlers import APIHandler
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import notebook_intelligence.extension as extension
from notebook_intelligence.extension import ChatHistory, GetChatHistoryHandler


class _DummyHistoryPersistence:
    def __init__(self, messages_by_chat_id):
        self._messages_by_chat_id = copy.deepcopy(messages_by_chat_id)

    async def get_messages_by_chat_id(self, chat_id, user_id=None):
        if isinstance(self._messages_by_chat_id.get(chat_id), dict):
            return copy.deepcopy(
                self._messages_by_chat_id.get(chat_id, {}).get(user_id, [])
            )
        return copy.deepcopy(self._messages_by_chat_id.get(chat_id, []))


def _set_history_mode(mode: str, persistence_messages=None):
    extension.ai_service_manager = SimpleNamespace(
        nbi_config=SimpleNamespace(history_config={"mode": mode}),
        history_persistence=_DummyHistoryPersistence(persistence_messages or {}),
    )


class TestChatHistoryHandler(AsyncHTTPTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        async def _noop(_self):
            return None

        cls._api_handler_patcher = patch.object(APIHandler, "prepare", _noop)
        cls._api_handler_patcher.start()
        cls._current_user_name = "test-user"
        cls._current_user_patcher = patch.object(
            APIHandler,
            "current_user",
            property(lambda _self: {"name": cls._current_user_name}),
        )
        cls._current_user_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._current_user_patcher.stop()
        cls._api_handler_patcher.stop()
        super().tearDownClass()

    def setUp(self):
        self._previous_ai_service_manager = extension.ai_service_manager
        self._previous_shared_chat_history = extension.shared_chat_history
        self._previous_ws_chat_history_ref = (
            extension.WebsocketCopilotHandler.chat_history_ref
        )
        type(self)._current_user_name = "test-user"
        super().setUp()

    def tearDown(self):
        extension.ai_service_manager = self._previous_ai_service_manager
        extension.shared_chat_history = self._previous_shared_chat_history
        extension.WebsocketCopilotHandler.chat_history_ref = (
            self._previous_ws_chat_history_ref
        )
        super().tearDown()

    def get_app(self):
        return Application([(r"/history", GetChatHistoryHandler)])

    def _get(self, chat_id: str):
        return self.fetch(
            f"/history?chatId={chat_id}",
            method="GET",
            raise_error=False,
        )

    def test_none_mode_returns_no_messages(self):
        _set_history_mode("none")
        response = self._get("chat-none")

        assert response.code == 200
        assert json.loads(response.body.decode("utf-8")) == {"messages": []}

    def test_local_mode_replays_in_memory_messages(self):
        _set_history_mode("local")
        history = ChatHistory()
        history.add_message(
            "chat-local", {"role": "user", "content": "hello"}, user_id="test-user"
        )
        history.add_message(
            "chat-local",
            {"role": "assistant", "content": "hi there"},
            user_id="test-user",
        )
        extension.shared_chat_history = history
        extension.WebsocketCopilotHandler.chat_history_ref = history

        response = self._get("chat-local")

        assert response.code == 200
        body = json.loads(response.body.decode("utf-8"))
        assert [message["content"] for message in body["messages"]] == [
            "hello",
            "hi there",
        ]

    def test_local_mode_does_not_leak_messages_from_other_user(self):
        _set_history_mode("local")
        history = ChatHistory()
        history.add_message(
            "chat-local", {"role": "user", "content": "hello from owner"}, user_id="owner"
        )
        history.add_message(
            "chat-local",
            {"role": "assistant", "content": "owner reply"},
            user_id="owner",
        )
        extension.shared_chat_history = history
        extension.WebsocketCopilotHandler.chat_history_ref = history
        type(self)._current_user_name = "viewer"

        response = self._get("chat-local")

        assert response.code == 200
        body = json.loads(response.body.decode("utf-8"))
        assert body["messages"] == []

    def test_persistent_mode_prefers_backend_history_over_longer_in_memory_copy(self):
        persisted_messages = {
            "chat-persistent": {
                "test-user": [
                    {
                        "role": "user",
                        "content": "show files",
                        "reasoning_content": None,
                        "tool_calls": None,
                        "tool_call_id": None,
                        "created_at": "2026-06-08T09:08:38+00:00",
                    },
                    {
                        "role": "assistant",
                        "content": "Here are the files.",
                        "reasoning_content": "Thinking",
                        "tool_calls": json.dumps(
                            [
                                {
                                    "type": "function",
                                    "id": "call_1",
                                    "function": {
                                        "name": "list_files",
                                        "arguments": "{\"directory\":\".\"}",
                                    },
                                }
                            ]
                        ),
                        "ui_parts": json.dumps([{"content": "Here are the files."}]),
                        "tool_call_id": None,
                        "created_at": "2026-06-08T09:08:53+00:00",
                    },
                ]
            }
        }
        _set_history_mode("persistent", persistence_messages=persisted_messages)

        history = ChatHistory()
        history.add_message(
            "chat-persistent", {"role": "user", "content": "stale copy"}
        )
        history.add_message(
            "chat-persistent",
            {"role": "assistant", "content": "stale assistant summary"},
        )
        history.add_message(
            "chat-persistent",
            {"role": "assistant", "content": "extra in-memory duplicate"},
        )
        extension.shared_chat_history = history
        extension.WebsocketCopilotHandler.chat_history_ref = history

        response = self._get("chat-persistent")

        assert response.code == 200
        body = json.loads(response.body.decode("utf-8"))
        assert [message["content"] for message in body["messages"]] == [
            "show files",
            "Here are the files.",
        ]
        assert body["messages"][1]["tool_calls"] == [
            {
                "type": "function",
                "id": "call_1",
                "function": {
                    "name": "list_files",
                    "arguments": "{\"directory\":\".\"}",
                },
            }
        ]
        assert body["messages"][1]["ui_parts"] == [{"content": "Here are the files."}]

    def test_persistent_mode_filters_by_current_user(self):
        persisted_messages = {
            "chat-persistent": {
                "owner": [
                    {
                        "role": "user",
                        "content": "owner secret",
                        "reasoning_content": None,
                        "tool_calls": None,
                        "tool_call_id": None,
                        "created_at": "2026-06-08T09:08:38+00:00",
                    }
                ]
            }
        }
        _set_history_mode("persistent", persistence_messages=persisted_messages)
        type(self)._current_user_name = "viewer"

        response = self._get("chat-persistent")

        assert response.code == 200
        body = json.loads(response.body.decode("utf-8"))
        assert body["messages"] == []
