# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import asyncio
import json
import logging
from typing import Any

from notebook_intelligence.history_backends.base import (
    HistoryBackendField,
    HistoryPersistenceBackend,
)

try:
    import aiomysql

    HAS_AIOMYSQL = True
except ImportError:
    aiomysql = None
    HAS_AIOMYSQL = False

log = logging.getLogger(__name__)


class MySQLHistoryBackend(HistoryPersistenceBackend):
    def __init__(self):
        self.pool = None
        self.loop = None
        self._lock_obj = None
        self.config: dict[str, Any] = {}
        self.host = "localhost"
        self.port = 3306
        self.user = ""
        self.password = ""
        self.database = "notebook_intelligence"

    @property
    def id(self) -> str:
        return "mysql"

    @property
    def name(self) -> str:
        return "MySQL"

    @property
    def description(self) -> str:
        return "Persist chat history to a remote MySQL database."

    @property
    def fields(self) -> list[HistoryBackendField]:
        return [
            HistoryBackendField("host", "Host", placeholder="localhost"),
            HistoryBackendField("port", "Port", input_type="number", placeholder="3306"),
            HistoryBackendField("user", "User", placeholder="root"),
            HistoryBackendField("password", "Password", input_type="password"),
            HistoryBackendField(
                "database", "Database", placeholder="notebook_intelligence"
            ),
        ]

    def configure(self, config: dict[str, Any]) -> None:
        new_config = config or {}
        if self.config == new_config:
            return

        if self.pool is not None:
            try:
                self.pool.close()
            except Exception:
                pass
            self.pool = None

        self.loop = None
        self._lock_obj = None
        self.config = dict(new_config)
        self.host = self.config.get("host", "localhost")
        self.port = int(self.config.get("port", 3306))
        self.user = self.config.get("user", "")
        self.password = self.config.get("password", "")
        self.database = self.config.get("database", "notebook_intelligence")

    def _get_lock(self):
        if self._lock_obj is None:
            self._lock_obj = asyncio.Lock()
        return self._lock_obj

    async def _get_pool(self):
        if not HAS_AIOMYSQL:
            return None

        if self.pool is not None:
            return self.pool

        if self.loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                return None

        async with self._get_lock():
            if self.pool is not None:
                return self.pool

            try:
                temp_conn = await aiomysql.connect(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    connect_timeout=3,
                    autocommit=True,
                )
                async with temp_conn.cursor() as cur:
                    await cur.execute(
                        f"CREATE DATABASE IF NOT EXISTS {self.database} CHARACTER SET utf8mb4;"
                    )
                temp_conn.close()

                self.pool = await aiomysql.create_pool(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    db=self.database,
                    connect_timeout=3,
                    autocommit=True,
                    charset="utf8mb4",
                )
                await self._ensure_tables()
                return self.pool
            except Exception as e:
                log.error("Failed to connect to MySQL history backend: %s", e)
                return None

    async def _ensure_tables(self):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS nbi_conversations (
                        id_pk INT AUTO_INCREMENT PRIMARY KEY,
                        id CHAR(36) UNIQUE,
                        user_id VARCHAR(255),
                        chat_id VARCHAR(255),
                        chat_mode VARCHAR(50),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                    """
                )
                await cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS nbi_messages (
                        id_pk INT AUTO_INCREMENT PRIMARY KEY,
                        id CHAR(36) UNIQUE,
                        conversation_id CHAR(36),
                        role VARCHAR(50),
                        content LONGTEXT,
                        reasoning_content LONGTEXT,
                        tool_calls JSON,
                        ui_parts JSON,
                        tool_call_id VARCHAR(255),
                        message_order_at DATETIME(6),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (conversation_id) REFERENCES nbi_conversations(id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                    """
                )
                try:
                    await cur.execute(
                        """
                        CREATE INDEX idx_nbi_messages_order_at
                        ON nbi_messages(message_order_at)
                        """
                    )
                except Exception as e:
                    if "Duplicate key name" not in str(e):
                        raise
                await cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS nbi_tool_executions (
                        id_pk INT AUTO_INCREMENT PRIMARY KEY,
                        id VARCHAR(255) UNIQUE,
                        conversation_id CHAR(36),
                        tool_name VARCHAR(255),
                        arguments JSON,
                        output LONGTEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (conversation_id) REFERENCES nbi_conversations(id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                    """
                )

    async def test_connection(self) -> tuple[bool, str]:
        if not HAS_AIOMYSQL:
            return False, "aiomysql is not installed."
        pool = await self._get_pool()
        if not pool:
            return False, f"Unable to connect to MySQL server {self.host}:{self.port}."
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
    ):
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
    ):
        pool = await self._get_pool()
        if not pool:
            return
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "INSERT IGNORE INTO nbi_conversations (id, user_id, chat_id, chat_mode) VALUES (%s, %s, %s, %s)",
                        (conv_id, user_id, chat_id, chat_mode),
                    )
        except Exception as e:
            log.error("Error creating conversation in MySQL history backend: %s", e)

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
    ):
        pool = await self._get_pool()
        if not pool:
            return
        try:
            tool_calls_json = json.dumps(tool_calls) if tool_calls else None
            ui_parts_json = json.dumps(ui_parts) if ui_parts else None
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT IGNORE INTO nbi_messages
                        (id, conversation_id, role, content, reasoning_content, tool_calls, ui_parts, tool_call_id, message_order_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))
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
                        ),
                    )
        except Exception as e:
            log.error("Error adding message to MySQL history backend: %s", e)

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
    ):
        pool = await self._get_pool()
        if not pool:
            return
        try:
            arguments_json = json.dumps(arguments)
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO nbi_tool_executions
                        (id, conversation_id, tool_name, arguments, output)
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE output = VALUES(output)
                        """,
                        (tool_call_id, conv_id, tool_name, arguments_json, output),
                    )
        except Exception as e:
            log.error("Error logging tool execution to MySQL history backend: %s", e)

    async def get_messages_by_chat_id(
        self, chat_id: str, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        if not pool:
            return []
        try:
            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    query = """
                        SELECT m.role, m.content, m.reasoning_content, m.tool_calls, m.ui_parts, m.tool_call_id, m.message_order_at, m.created_at
                        FROM nbi_messages m
                        JOIN nbi_conversations c ON m.conversation_id = c.id
                        WHERE c.chat_id = %s
                    """
                    params: tuple[Any, ...] = (chat_id,)
                    if user_id is not None:
                        query += " AND c.user_id = %s"
                        params += (user_id,)
                    query += " ORDER BY m.message_order_at ASC"
                    await cur.execute(query, params)
                    return await cur.fetchall()
        except Exception as e:
            log.error("Error getting messages from MySQL history backend: %s", e)
            return []

    async def get_recent_conversations(
        self, user_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        if not pool:
            return []
        try:
            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        """
                        SELECT c.chat_id, c.chat_mode, MAX(COALESCE(m.created_at, c.created_at)) as last_message_at
                        FROM nbi_conversations c
                        LEFT JOIN nbi_messages m ON m.conversation_id = c.id
                        WHERE c.user_id = %s
                        GROUP BY c.chat_id, c.chat_mode
                        ORDER BY last_message_at DESC
                        LIMIT %s
                        """,
                        (user_id, limit),
                    )
                    return await cur.fetchall()
        except Exception as e:
            log.error(
                "Error getting recent conversations from MySQL history backend: %s",
                e,
            )
            return []
