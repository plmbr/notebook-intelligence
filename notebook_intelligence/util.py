# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import os
import base64
import shutil
import subprocess
from typing import Optional, Set
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet
import asyncio
from tornado import ioloop

_jupyter_root_dir: str = None
_enabled_tools: Set[str] = None

def set_jupyter_root_dir(root_dir: str):
    global _jupyter_root_dir
    _jupyter_root_dir = root_dir

def get_jupyter_root_dir() -> str:
    return _jupyter_root_dir


_UNSET = object()
_cached_which_claude: object = _UNSET


def resolve_claude_cli_path() -> Optional[str]:
    """Resolve the Claude Code CLI binary path.

    NBI_CLAUDE_CLI_PATH wins when set; otherwise fall back to the first
    `claude` on PATH. Returns None when nothing is found, so callers can
    decide between raising and proceeding without the CLI.

    The PATH lookup is memoized — capabilities is hot and PATH doesn't
    change at runtime. Use ``invalidate_claude_cli_cache`` from tests.
    """
    explicit = os.getenv("NBI_CLAUDE_CLI_PATH")
    if explicit:
        return explicit
    global _cached_which_claude
    if _cached_which_claude is _UNSET:
        _cached_which_claude = shutil.which("claude")
    return _cached_which_claude  # type: ignore[return-value]


def invalidate_claude_cli_cache() -> None:
    global _cached_which_claude
    _cached_which_claude = _UNSET


def resolve_github_token() -> Optional[str]:
    """Look up a GitHub token for repo / API auth.

    Order matches the gh CLI's own precedence: GITHUB_TOKEN, then GH_TOKEN,
    then whatever ``gh auth token`` returns. The gh-CLI fallback lets users
    in corporate/SSO environments inherit their existing login without
    setting an env var — important when the JupyterLab server is started
    by JupyterHub / a service manager that doesn't preserve the user's
    interactive shell environment.
    """
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(var)
        if token and token.strip():
            return token.strip()
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    # `gh auth token` should print one line, but defensively take only the
    # first non-empty line so a malformed install doesn't smuggle extra
    # bytes into the token.
    for line in result.stdout.splitlines():
        token = line.strip()
        if token:
            return token
    return None

def extract_llm_generated_code(code: str) -> str:
    if code.endswith("```"):
        code = code[:-3]

    lines = code.split("\n")
    if len(lines) < 2:
        return code

    num_lines = len(lines)
    start_line = -1
    end_line = num_lines

    for i in range(num_lines):
        if start_line == -1:
            if lines[i].lstrip().startswith("```"):
                start_line = i
                continue
        else:
            if lines[i].lstrip().startswith("```"):
                end_line = i
                break

    if start_line != -1:
        lines = lines[start_line+1:end_line]

    return "\n".join(lines)

def encrypt_with_password(password: str, data: bytes) -> bytes:
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=1200000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    f = Fernet(key)
    encrypted_data = f.encrypt(data)

    return salt + encrypted_data

def decrypt_with_password(password: str, encrypted_data_with_salt: bytes) -> bytes:
    salt = encrypted_data_with_salt[:16]
    encrypted_data = encrypted_data_with_salt[16:]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=1200000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    f = Fernet(key)
    decrypted_data = f.decrypt(encrypted_data)

    return decrypted_data

def get_enabled_builtin_tools_in_env() -> Set[str]:
  global _enabled_tools
  if _enabled_tools is not None:
    return _enabled_tools
  
  # load enabled built-in tools from environment variable
  _enabled_tools = set()
  enabled_tools_list = os.getenv('NBI_ENABLED_BUILTIN_TOOLS', '').split(',')
  for tool in enabled_tools_list:
    tool = tool.strip() 
    if tool:
      _enabled_tools.add(tool)
  return _enabled_tools

def is_builtin_tool_enabled_in_env(tool: str) -> bool:
  return tool in get_enabled_builtin_tools_in_env()

def is_provider_enabled_in_env(provider_id: str) -> bool:
    enabled_providers = os.environ.get('NBI_ENABLED_PROVIDERS', '')
    return provider_id in enabled_providers.split(',')

def _emit(signal, payload: dict) -> None:
    if signal is not None:
        signal.emit(payload)


class ThreadSafeWebSocketConnector():
  def __init__(self, websocket_handler):
    self.io_loop = ioloop.IOLoop.current()
    self.websocket_handler = websocket_handler

  def write_message(self, message: dict):
    def _write_message():
        self.websocket_handler.write_message(message)
    asyncio.set_event_loop(self.io_loop.asyncio_loop)
    self.io_loop.asyncio_loop.call_soon_threadsafe(_write_message)

  def schedule(self, callback, *args):
    """Schedule a callback on the Tornado asyncio loop from any thread."""
    self.io_loop.asyncio_loop.call_soon_threadsafe(callback, *args)
