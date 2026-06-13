import asyncio
import datetime as dt
import json
import logging
import os
import sqlite3
from typing import Any

from notebook_intelligence.history_backends.base import (
    HistoryBackendField,
    HistoryPersistenceBackend,
)

log = logging.getLogger(__name__)


class SQLiteHistoryBackend(HistoryPersistenceBackend):
    def __init__(self):
        self.loop = None
        self.config: dict[str, Any] = {}
        self.path = ""

    @property
    def id(self) -> str:
        return "sqlite"

    @property
    def name(self) -> str:
        return "SQLite"

    @property
    def description(self) -> str:
        return "Persist chat history to a local SQLite file."

    @property
    def fields(self) -> list[HistoryBackendField]:
        return [
            HistoryBackendField(
                "path",
                "Database path",
                placeholder="~/.jupyter/nbi/history.sqlite3",
                help_text="Absolute or home-relative path to the SQLite file.",
            )
        ]

    def configure(self, config: dict[str, Any]) -> None:
        self.config = dict(config or {})
        self.path = os.path.expanduser(self.config.get("path", "")).strip()

    def _ensure_db_path(self) -> tuple[bool, str]:
        if not self.path:
            return False, "SQLite database path is empty."
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except Exception as e:
            return False, f"Failed to create SQLite directory: {e}"
        return True, ""

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_tables_sync(self) -> None:
        ok, err = self._ensure_db_path()
        if not ok:
            raise RuntimeError(err)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nbi_conversations (
                    id_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT UNIQUE,
                    user_id TEXT,
                    chat_id TEXT,
                    chat_mode TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nbi_messages (
                    id_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT UNIQUE,
                    conversation_id TEXT,
                    role TEXT,
                    content TEXT,
                    reasoning_content TEXT,
                    tool_calls TEXT,
                    ui_parts TEXT,
                    tool_call_id TEXT,
                    message_order_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES nbi_conversations(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_nbi_messages_order_at
                ON nbi_messages(message_order_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nbi_tool_executions (
                    id_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT UNIQUE,
                    conversation_id TEXT,
                    tool_name TEXT,
                    arguments TEXT,
                    output TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES nbi_conversations(id)
                )
                """
            )
            conn.commit()

    async def test_connection(self) -> tuple[bool, str]:
        try:
            self._ensure_tables_sync()
        except Exception as e:
            return False, str(e)
        return True, ""

    def _run_task(self, coro):
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if self.loop and current_loop != self.loop:
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        else:
            if self.loop is None:
                self.loop = current_loop
            asyncio.create_task(coro)

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
        self._run_task(
            self._create_conversation_with_message_internal(
                conv_id, user_id, chat_id, chat_mode, msg_id, role, content
            )
        )

    async def _create_conversation_with_message_internal(
        self,
        conv_id: str,
        user_id: str,
        chat_id: str,
        chat_mode: str,
        msg_id: str,
        role: str,
        content: str,
    ) -> None:
        await self._create_conversation_internal(conv_id, user_id, chat_id, chat_mode)
        await self._add_message_internal(msg_id, conv_id, role, content)

    def create_conversation(
        self, conv_id: str, user_id: str, chat_id: str, chat_mode: str
    ) -> None:
        self._run_task(
            self._create_conversation_internal(conv_id, user_id, chat_id, chat_mode)
        )

    async def _create_conversation_internal(
        self, conv_id: str, user_id: str, chat_id: str, chat_mode: str
    ) -> None:
        try:
            self._ensure_tables_sync()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO nbi_conversations (id, user_id, chat_id, chat_mode)
                    VALUES (?, ?, ?, ?)
                    """,
                    (conv_id, user_id, chat_id, chat_mode),
                )
                conn.commit()
        except Exception as e:
            log.error("Error creating conversation in SQLite history backend: %s", e)

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
        if (
            not content
            and not reasoning_content
            and not tool_calls
            and not ui_parts
            and not tool_call_id
        ):
            return
        self._run_task(
            self._add_message_internal(
                message_id,
                conv_id,
                role,
                content,
                reasoning_content,
                tool_calls,
                ui_parts,
                tool_call_id,
            )
        )

    async def _add_message_internal(
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
        try:
            self._ensure_tables_sync()
            tool_calls_json = json.dumps(tool_calls) if tool_calls else None
            ui_parts_json = json.dumps(ui_parts) if ui_parts else None
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO nbi_messages
                    (id, conversation_id, role, content, reasoning_content, tool_calls, ui_parts, tool_call_id, message_order_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        conv_id,
                        role,
                        content,
                        reasoning_content,
                        tool_calls_json,
                        ui_parts_json,
                        tool_call_id,
                        dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds"),
                    ),
                )
                conn.commit()
        except Exception as e:
            log.error("Error adding message to SQLite history backend: %s", e)

    def log_tool_execution(
        self, tool_call_id: str, conv_id: str, tool_name: str, arguments: dict, output: str
    ) -> None:
        self._run_task(
            self._log_tool_execution_internal(
                tool_call_id, conv_id, tool_name, arguments, output
            )
        )

    async def _log_tool_execution_internal(
        self, tool_call_id: str, conv_id: str, tool_name: str, arguments: dict, output: str
    ) -> None:
        try:
            self._ensure_tables_sync()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO nbi_tool_executions (id, conversation_id, tool_name, arguments, output)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET output = excluded.output
                    """,
                    (tool_call_id, conv_id, tool_name, json.dumps(arguments), output),
                )
                conn.commit()
        except Exception as e:
            log.error("Error logging tool execution to SQLite history backend: %s", e)

    async def get_messages_by_chat_id(
        self, chat_id: str, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        try:
            self._ensure_tables_sync()
            with self._connect() as conn:
                query = """
                    SELECT m.role, m.content, m.reasoning_content, m.tool_calls, m.ui_parts, m.tool_call_id, m.message_order_at, m.created_at
                    FROM nbi_messages m
                    JOIN nbi_conversations c ON m.conversation_id = c.id
                    WHERE c.chat_id = ?
                """
                params: tuple[Any, ...] = (chat_id,)
                if user_id is not None:
                    query += " AND c.user_id = ?"
                    params += (user_id,)
                query += " ORDER BY m.message_order_at ASC"
                rows = conn.execute(query, params).fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            log.error("Error getting messages from SQLite history backend: %s", e)
            return []

    async def get_recent_conversations(
        self, user_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        try:
            self._ensure_tables_sync()
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT c.chat_id, c.chat_mode,
                           MAX(COALESCE(m.created_at, c.created_at)) as last_message_at
                    FROM nbi_conversations c
                    LEFT JOIN nbi_messages m ON m.conversation_id = c.id
                    WHERE c.user_id = ?
                    GROUP BY c.chat_id, c.chat_mode
                    ORDER BY last_message_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            log.error(
                "Error getting recent conversations from SQLite history backend: %s",
                e,
            )
            return []
