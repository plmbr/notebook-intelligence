# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import json
import logging
import uuid
import datetime
import asyncio
from typing import Optional, List, Dict, Any

try:
    import aiomysql
    HAS_AIOMYSQL = True
except ImportError:
    aiomysql = None
    HAS_AIOMYSQL = False

log = logging.getLogger(__name__)

class MySQLManager:
    _instance = None
    _lock = None

    def __new__(cls, config=None):
        if cls._instance is None:
            cls._instance = super(MySQLManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config=None):
        config = config or {}
        if not self._initialized:
            self.pool = None
            self.loop = None
            self._lock_obj = None
            self.config = {}
            self.enabled = False
            self.host = 'localhost'
            self.port = 3306
            self.user = ''
            self.password = ''
            self.database = 'notebook_intelligence'
            self._initialized = True

        self._apply_config(config)

    def _apply_config(self, config: dict):
        new_config = config or {}
        if getattr(self, "config", {}) == new_config:
            return

        # Close old pool handle when switching configs.
        if self.pool is not None:
            try:
                self.pool.close()
            except Exception:
                pass
            self.pool = None

        self.loop = None
        self._lock_obj = None
        self.config = new_config
        self.enabled = self.config.get('enabled', False) and HAS_AIOMYSQL
        self.host = self.config.get('host', 'localhost')
        self.port = self.config.get('port', 3306)
        self.user = self.config.get('user', '')
        self.password = self.config.get('password', '')
        self.database = self.config.get('database', 'notebook_intelligence')

        if self.enabled:
            log.info(f"MySQL logging enabled for host: {self.host}")
        elif self.config.get('enabled', False):
            log.error("aiomysql not found. Please install it with 'pip install aiomysql' to use MySQL logging.")
        else:
            log.info("MySQL logging disabled.")
        
    def _get_lock(self):
        if self._lock_obj is None:
            self._lock_obj = asyncio.Lock()
        return self._lock_obj

    async def _get_pool(self):
        if not self.enabled or not HAS_AIOMYSQL:
            return None
        
        if self.pool is not None:
            return self.pool
        
        # Capture the loop that initializes the pool
        if self.loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                # Fallback for cases where loop isn't running yet
                return None

        async with self._get_lock():
            if self.pool is not None:
                return self.pool
                
            try:
                # First, connect without db to ensure database exists
                temp_conn = await aiomysql.connect(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    connect_timeout=3,
                    autocommit=True
                )
                async with temp_conn.cursor() as cur:
                    await cur.execute(f"CREATE DATABASE IF NOT EXISTS {self.database} CHARACTER SET utf8mb4;")
                temp_conn.close()

                # Now connect to the pool with the database
                self.pool = await aiomysql.create_pool(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    db=self.database,
                    connect_timeout=3,
                    autocommit=True,
                    charset='utf8mb4'
                )
                await self._ensure_tables()
                return self.pool
            except Exception as e:
                log.error(f"Failed to connect to MySQL: {str(e)}")
                self.enabled = False
                return None

    async def _ensure_tables(self):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Conversations table with auto-incrementing ID
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS nbi_conversations (
                        id_pk INT AUTO_INCREMENT PRIMARY KEY,
                        id CHAR(36) UNIQUE,
                        user_id VARCHAR(255),
                        chat_id VARCHAR(255),
                        chat_mode VARCHAR(50),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)
                
                # Messages table with auto-incrementing ID
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS nbi_messages (
                        id_pk INT AUTO_INCREMENT PRIMARY KEY,
                        id CHAR(36) UNIQUE,
                        conversation_id CHAR(36),
                        role VARCHAR(50),
                        content LONGTEXT,
                        reasoning_content LONGTEXT,
                        tool_calls JSON,
                        tool_call_id VARCHAR(255),
                        message_order_at DATETIME(6),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (conversation_id) REFERENCES nbi_conversations(id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)
                try:
                    await cur.execute("""
                        CREATE INDEX idx_nbi_messages_order_at
                        ON nbi_messages(message_order_at)
                    """)
                except Exception as e:
                    # MySQL raises duplicate-key error when the index already
                    # exists. Keep initialization idempotent across re-enables.
                    if "Duplicate key name" not in str(e):
                        raise
                
                # Tool executions table with auto-incrementing ID
                await cur.execute("""
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
                """)

    async def test_connection(self) -> tuple[bool, str]:
        """Validate MySQL connectivity and table initialization."""
        if not self.config.get('enabled', False):
            return False, "MySQL is not enabled in configuration."
        if not HAS_AIOMYSQL:
            return False, "aiomysql is not installed."

        # Force a fresh attempt when validating.
        self.enabled = True
        pool = await self._get_pool()
        if not pool:
            return False, f"Unable to connect to MySQL server {self.host}:{self.port}."
        return True, ""

    def _run_task(self, coro):
        """Run a coroutine in the correct event loop."""
        if not self.enabled:
            return
        
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            # If no loop is running in this thread, we need to handle it
            # For now, we assume the first call happened in a thread with a loop (like Tornado)
            return

        if self.loop and current_loop != self.loop:
            # Schedule on the pool's home loop
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        else:
            # Already in the right loop or first call
            asyncio.create_task(coro)

    def create_conversation_with_message(self, conv_id: str, user_id: str, chat_id: str, chat_mode: str,
                                            msg_id: str, role: str, content: str):
        if not self.enabled:
            return
        self._run_task(self._create_conversation_with_message_internal(conv_id, user_id, chat_id, chat_mode, msg_id, role, content))

    async def _create_conversation_with_message_internal(self, conv_id: str, user_id: str, chat_id: str, chat_mode: str,
                                            msg_id: str, role: str, content: str):
        await self._create_conversation_internal(conv_id, user_id, chat_id, chat_mode)
        await self._add_message_internal(msg_id, conv_id, role, content)

    def create_conversation(self, conv_id: str, user_id: str, chat_id: str, chat_mode: str):
        if not self.enabled:
            return
        self._run_task(self._create_conversation_internal(conv_id, user_id, chat_id, chat_mode))

    async def _create_conversation_internal(self, conv_id: str, user_id: str, chat_id: str, chat_mode: str):
        pool = await self._get_pool()
        if not pool: return
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "INSERT IGNORE INTO nbi_conversations (id, user_id, chat_id, chat_mode) VALUES (%s, %s, %s, %s)",
                        (conv_id, user_id, chat_id, chat_mode)
                    )
        except Exception as e:
            log.error(f"Error creating conversation in MySQL: {str(e)}")

    def add_message(self, message_id: str, conv_id: str, role: str, content: str, 
                         reasoning_content: Optional[str] = None, 
                         tool_calls: Optional[List[Dict]] = None,
                         tool_call_id: Optional[str] = None):
        if not self.enabled:
            return
        # Skip logging if message is completely empty
        if not content and not reasoning_content and not tool_calls and not tool_call_id:
            return
        self._run_task(self._add_message_internal(message_id, conv_id, role, content, reasoning_content, tool_calls, tool_call_id))

    async def _add_message_internal(self, message_id: str, conv_id: str, role: str, content: str, 
                         reasoning_content: Optional[str] = None, 
                         tool_calls: Optional[List[Dict]] = None,
                         tool_call_id: Optional[str] = None):
        pool = await self._get_pool()
        if not pool: return
        try:
            tool_calls_json = json.dumps(tool_calls) if tool_calls else None
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """INSERT IGNORE INTO nbi_messages 
                           (id, conversation_id, role, content, reasoning_content, tool_calls, tool_call_id, message_order_at) 
                           VALUES (%s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))""",
                        (message_id, conv_id, role, content, reasoning_content, tool_calls_json, tool_call_id)
                    )
        except Exception as e:
            log.error(f"Error adding message to MySQL: {str(e)}")

    def log_tool_execution(self, tool_call_id: str, conv_id: str, tool_name: str, 
                                arguments: Dict, output: str):
        if not self.enabled:
            return
        self._run_task(self._log_tool_execution_internal(tool_call_id, conv_id, tool_name, arguments, output))

    async def _log_tool_execution_internal(self, tool_call_id: str, conv_id: str, tool_name: str, 
                                arguments: Dict, output: str):
        pool = await self._get_pool()
        if not pool: return
        try:
            arguments_json = json.dumps(arguments)
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Use INSERT ... ON DUPLICATE KEY UPDATE in case output is updated later
                    await cur.execute(
                        """INSERT INTO nbi_tool_executions 
                           (id, conversation_id, tool_name, arguments, output) 
                           VALUES (%s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE output = VALUES(output)""",
                        (tool_call_id, conv_id, tool_name, arguments_json, output)
                    )
        except Exception as e:
            log.error(f"Error logging tool execution to MySQL: {str(e)}")

    async def get_messages_by_chat_id(self, chat_id: str) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        if not pool: return []
        try:
            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        """SELECT m.role, m.content, m.reasoning_content, m.tool_calls, m.tool_call_id, m.created_at
                           FROM nbi_messages m
                           JOIN nbi_conversations c ON m.conversation_id = c.id
                           WHERE c.chat_id = %s
                           ORDER BY m.message_order_at ASC""",
                        (chat_id,)
                    )
                    return await cur.fetchall()
        except Exception as e:
            log.error(f"Error getting messages from MySQL: {str(e)}")
            return []

    async def get_recent_conversations(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        if not pool: return []
        try:
            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        """SELECT chat_id, chat_mode, MAX(created_at) as last_message_at
                           FROM nbi_conversations
                           WHERE user_id = %s
                           GROUP BY chat_id, chat_mode
                           ORDER BY last_message_at DESC
                           LIMIT %s""",
                        (user_id, limit)
                    )
                    return await cur.fetchall()
        except Exception as e:
            log.error(f"Error getting recent conversations from MySQL: {str(e)}")
            return []
