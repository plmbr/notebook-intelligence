import copy
from dataclasses import dataclass
from typing import Any


@dataclass
class HistoryBackendField:
    key: str
    label: str
    input_type: str = "text"
    placeholder: str = ""
    help_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "input_type": self.input_type,
            "placeholder": self.placeholder,
            "help_text": self.help_text,
        }


class HistoryPersistenceBackend:
    @property
    def id(self) -> str:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def description(self) -> str:
        return ""

    @property
    def fields(self) -> list[HistoryBackendField]:
        return []

    def configure(self, config: dict[str, Any]) -> None:
        raise NotImplementedError

    async def test_connection(self) -> tuple[bool, str]:
        raise NotImplementedError

    def create_conversation_with_message(
        self,
        conv_id: str,
        user_id: str,
        chat_id: str,
        chat_mode: str,
        msg_id: str,
        role: str,
        content: str,
    ) -> None:
        raise NotImplementedError

    def create_conversation(
        self, conv_id: str, user_id: str, chat_id: str, chat_mode: str
    ) -> None:
        raise NotImplementedError

    def add_message(
        self,
        message_id: str,
        conv_id: str,
        role: str,
        content: str,
        reasoning_content: str | None = None,
        tool_calls: list[dict] | None = None,
        ui_parts: list[dict] | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        raise NotImplementedError

    def log_tool_execution(
        self,
        tool_call_id: str,
        conv_id: str,
        tool_name: str,
        arguments: dict,
        output: str,
    ) -> None:
        raise NotImplementedError

    async def get_messages_by_chat_id(
        self, chat_id: str, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def get_recent_conversations(
        self, user_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "fields": [field.to_dict() for field in self.fields],
        }


class HistoryPersistenceManager:
    def __init__(self):
        self._backends: dict[str, HistoryPersistenceBackend] = {}
        self._history_config: dict[str, Any] = {}
        self._backend_configs: dict[str, dict[str, Any]] = {}

    def register_backend(self, backend: HistoryPersistenceBackend) -> None:
        if backend.id in self._backends:
            raise ValueError(f"History backend '{backend.id}' is already registered.")
        self._backends[backend.id] = backend
        backend.configure(copy.deepcopy(self._backend_configs.get(backend.id, {})))

    def reconfigure(
        self,
        history_config: dict[str, Any],
        backend_configs: dict[str, dict[str, Any]],
    ) -> None:
        self._history_config = self._coerce_dict(history_config)
        self._backend_configs = self._coerce_nested_dict(backend_configs)
        for backend in self._backends.values():
            backend.configure(copy.deepcopy(self._backend_configs.get(backend.id, {})))

    @staticmethod
    def _coerce_dict(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @classmethod
    def _coerce_nested_dict(cls, value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, dict):
            return {}
        result = {}
        for key, nested in value.items():
            result[key] = dict(nested) if isinstance(nested, dict) else {}
        return result

    @property
    def mode(self) -> str:
        return self._history_config.get("mode", "local")

    @property
    def backend_id(self) -> str:
        return self._history_config.get("backend", "")

    @property
    def backend_configs(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._backend_configs)

    @property
    def active_backend(self) -> HistoryPersistenceBackend | None:
        if self.mode != "persistent":
            return None
        return self._backends.get(self.backend_id)

    def available_backends(self) -> list[dict[str, Any]]:
        return [backend.to_wire() for backend in self._backends.values()]

    async def test_connection(self) -> tuple[bool, str]:
        if self.mode != "persistent":
            return False, "History persistence is not enabled."
        backend = self.active_backend
        if backend is None:
            return False, f"Unknown history backend '{self.backend_id}'."
        return await backend.test_connection()

    def create_conversation_with_message(
        self,
        conv_id: str,
        user_id: str,
        chat_id: str,
        chat_mode: str,
        msg_id: str,
        role: str,
        content: str,
    ) -> None:
        backend = self.active_backend
        if backend is not None:
            backend.create_conversation_with_message(
                conv_id, user_id, chat_id, chat_mode, msg_id, role, content
            )

    def create_conversation(
        self, conv_id: str, user_id: str, chat_id: str, chat_mode: str
    ) -> None:
        backend = self.active_backend
        if backend is not None:
            backend.create_conversation(conv_id, user_id, chat_id, chat_mode)

    def add_message(
        self,
        message_id: str,
        conv_id: str,
        role: str,
        content: str,
        reasoning_content: str | None = None,
        tool_calls: list[dict] | None = None,
        ui_parts: list[dict] | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        backend = self.active_backend
        if backend is not None:
            backend.add_message(
                message_id,
                conv_id,
                role,
                content,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls,
                ui_parts=ui_parts,
                tool_call_id=tool_call_id,
            )

    def log_tool_execution(
        self,
        tool_call_id: str,
        conv_id: str,
        tool_name: str,
        arguments: dict,
        output: str,
    ) -> None:
        backend = self.active_backend
        if backend is not None:
            backend.log_tool_execution(
                tool_call_id, conv_id, tool_name, arguments, output
            )

    async def get_messages_by_chat_id(
        self, chat_id: str, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        backend = self.active_backend
        if backend is None:
            return []
        return await backend.get_messages_by_chat_id(chat_id, user_id=user_id)

    async def get_recent_conversations(
        self, user_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        backend = self.active_backend
        if backend is None:
            return []
        return await backend.get_recent_conversations(user_id, limit=limit)
