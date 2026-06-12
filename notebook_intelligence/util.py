# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import os
import base64
import logging
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional, Set
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet
import asyncio
from tornado import ioloop

try:
    import psutil
except ImportError:  # psutil is optional; we degrade to a single-process kill
    psutil = None

log = logging.getLogger(__name__)

_jupyter_root_dir: str = None
_enabled_tools: Set[str] = None

def import_litellm():
    """Import litellm on first use instead of at server-extension import.

    litellm is over a second of import time (the largest single chunk of
    NBI's startup) and, by default, fetches its model-cost map over HTTP at
    import, which can stall on proxied networks. Defaulting
    LITELLM_LOCAL_MODEL_COST_MAP to true makes it read the map bundled with
    the installed litellm instead; set the env var to false to restore the
    remote fetch.
    """
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    import litellm
    return litellm

def set_jupyter_root_dir(root_dir: str):
    global _jupyter_root_dir
    _jupyter_root_dir = root_dir

def get_jupyter_root_dir() -> str:
    return _jupyter_root_dir


def safe_jupyter_path(path: str) -> Path:
    """Resolve ``path`` and confirm it stays inside ``jupyter_root_dir``.

    The single chokepoint every tool / handler should funnel an LLM-supplied
    path through before handing it to ``subprocess.Popen(cwd=...)``,
    ``docmanager:open``, ``terminal:create-new``, or any other shell- or
    UI-bridge that would otherwise honor an absolute path or a ``..``
    traversal. Relative paths are interpreted relative to the workspace
    root. ``Path.resolve()`` collapses ``..`` segments and chases symlinks
    before the containment check, so a workspace-internal symlink
    pointing outside is also rejected.

    Returns the resolved absolute ``Path``. Raises ``ValueError`` when the
    LLM-supplied input is rejected (outside the workspace, embedded NUL,
    or otherwise unrepresentable). Raises ``RuntimeError`` for the
    "workspace root not set" case so callers that do ``except ValueError``
    to surface a sandbox-violation message to the LLM don't accidentally
    swallow a server-side misconfiguration as if it were user input.
    Callers handle existence / file-vs-directory checks themselves so
    they can produce the contextual error message the LLM needs to
    correct its tool call.
    """
    jupyter_root_dir = get_jupyter_root_dir()
    if jupyter_root_dir is None:
        raise RuntimeError(
            "Jupyter root directory is not set; "
            "set_jupyter_root_dir was not called before this code path."
        )

    root_dir = Path(jupyter_root_dir).expanduser().resolve()
    target_path = Path(path).expanduser()

    if not target_path.is_absolute():
        target_path = root_dir / target_path

    target_path = target_path.resolve()

    try:
        target_path.relative_to(root_dir)
    except ValueError:
        raise ValueError(
            f"Path '{path}' is outside allowed directory '{jupyter_root_dir}'"
        )

    return target_path


def get_claude_config_dir() -> str:
    """Claude Code's config dir: CLAUDE_CONFIG_DIR when set, else ``~/.claude``.

    Mirrors the CLI's own override so every surface that reads CLI-owned
    state (session transcripts, skills, settings.json) looks where the CLI
    actually writes. Read per call rather than memoized: it's a dict lookup,
    and tests toggle the env var between cases.
    """
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude"
    )


_cached_cli_paths: dict[str, Optional[str]] = {}


def _resolve_cli_path(name: str, env_var: str) -> Optional[str]:
    """Resolve an agent-CLI binary path with env override + PATH fallback.

    The env var wins when set; otherwise this is a memoized shutil.which.
    Capabilities is a hot endpoint and PATH doesn't change at runtime, so
    every lookup goes through this single cache. Tests should call
    ``invalidate_cli_cache`` between cases that toggle the env or PATH.
    """
    explicit = os.getenv(env_var)
    if explicit:
        return explicit
    if name not in _cached_cli_paths:
        _cached_cli_paths[name] = shutil.which(name)
    return _cached_cli_paths[name]


def resolve_claude_cli_path() -> Optional[str]:
    """Claude Code CLI. NBI_CLAUDE_CLI_PATH overrides; else `claude` on PATH."""
    return _resolve_cli_path("claude", "NBI_CLAUDE_CLI_PATH")


def resolve_opencode_cli_path() -> Optional[str]:
    """opencode CLI. NBI_OPENCODE_CLI_PATH overrides; else `opencode` on PATH."""
    return _resolve_cli_path("opencode", "NBI_OPENCODE_CLI_PATH")


def resolve_pi_cli_path() -> Optional[str]:
    """Pi CLI. NBI_PI_CLI_PATH overrides; else `pi` on PATH."""
    return _resolve_cli_path("pi", "NBI_PI_CLI_PATH")


def resolve_copilot_cli_path() -> Optional[str]:
    """GitHub Copilot CLI. NBI_GITHUB_COPILOT_CLI_PATH overrides; else `copilot` on PATH."""
    return _resolve_cli_path("copilot", "NBI_GITHUB_COPILOT_CLI_PATH")


def resolve_codex_cli_path() -> Optional[str]:
    """OpenAI Codex CLI. NBI_CODEX_CLI_PATH overrides; else `codex` on PATH."""
    return _resolve_cli_path("codex", "NBI_CODEX_CLI_PATH")


def invalidate_cli_cache(name: Optional[str] = None) -> None:
    """Clear the memoized CLI-path cache. Pass a name to invalidate just one."""
    if name is None:
        _cached_cli_paths.clear()
    else:
        _cached_cli_paths.pop(name, None)


# Seconds to wait after SIGTERM before escalating to SIGKILL during teardown.
_TEARDOWN_GRACE_SECONDS = 3.0


def _signal_proc(proc, *, force: bool) -> None:
    """Signal one psutil process, swallowing the races that are expected here."""
    try:
        proc.kill() if force else proc.terminate()
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied as e:
        log.warning("No permission to signal pid %s during teardown: %s", proc.pid, e)


def terminate_process_tree(
    pid: Optional[int], grace_seconds: float = _TEARDOWN_GRACE_SECONDS
) -> None:
    """Terminate ``pid`` and every descendant, gracefully then forcefully.

    Sends SIGTERM to the whole tree, waits up to ``grace_seconds`` for exits,
    then SIGKILLs any survivors. This tears down an agent subprocess along with
    everything it spawned (shells, MCP servers, dev servers) that a bare
    child-only kill would orphan.

    Signals are sent per-PID, never to a process group: the agent subprocess is
    spawned inside this server's own process group, so a group signal would also
    hit the Jupyter server. Safe to call with a missing or already-dead pid.
    Without psutil only ``pid`` itself is terminated (descendants can't be
    discovered), which still adds a graceful step over a bare SIGKILL.

    Never raises: this is run fire-and-forget from a background thread, so any
    unexpected failure is logged rather than propagated.
    """
    if not pid or pid <= 0:
        return

    if psutil is None:
        _terminate_pid_without_psutil(pid, grace_seconds)
        return

    try:
        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return

        # Snapshot descendants before signalling: once the parent dies its
        # children are reparented to init and the tree linkage is lost.
        try:
            procs = parent.children(recursive=True)
        except psutil.NoSuchProcess:
            procs = []
        procs.append(parent)

        for proc in procs:
            _signal_proc(proc, force=False)

        _, alive = psutil.wait_procs(procs, timeout=max(0.0, grace_seconds))
        for proc in alive:
            _signal_proc(proc, force=True)
        if alive:
            psutil.wait_procs(alive, timeout=max(0.0, grace_seconds))
    except Exception:
        log.exception("Failed to terminate process tree for pid %s", pid)


def _terminate_pid_without_psutil(pid: int, grace_seconds: float) -> None:
    """Graceful kill of a single pid for the rare environment without psutil.

    Cannot discover descendants, so this only improves on a bare SIGKILL by
    adding a SIGTERM grace period; grandchildren may still be orphaned. This
    path is POSIX-shaped: on Windows ``os.kill`` routes any signal through
    TerminateProcess, so the SIGTERM grace and the SIGKILL escalation collapse
    into a single hard kill (still terminates ``pid``, just not gracefully).
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)  # probe: raises once the process is gone
        except OSError:
            return
        time.sleep(0.05)
    sigkill = getattr(signal, "SIGKILL", None)  # absent on Windows
    if sigkill is not None:
        try:
            os.kill(pid, sigkill)
        except (ProcessLookupError, OSError):
            pass


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

def split_csv(raw) -> list:
    """Parse a comma-separated string into a list of stripped, non-empty tokens.

    Used by env-var and traitlet resolvers across the codebase that share
    the "comma-separated, whitespace-tolerant, empty-dropping" wire format
    (e.g. NBI_ENABLED_PROVIDERS, NBI_SKILLS_MANIFEST,
    NBI_ADDITIONAL_SKIPPED_WORKSPACE_DIRECTORIES). Non-string input
    degrades to ``[]`` so a traitlet that yields None doesn't crash the
    resolver. Caller is responsible for any subsequent dedupe.
    """
    if not isinstance(raw, str):
        return []
    return [token for token in (part.strip() for part in raw.split(",")) if token]


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


# Schemes safe to emit into the chat anchor stream. Anchors are populated
# from arbitrary LLM / tool output, and React does not block javascript:,
# data:, vbscript:, etc. in href attributes; rel=noopener also does not
# prevent javascript: execution against the parent origin. Keep this
# allowlist tight; the frontend re-checks before assigning href as
# defense in depth.
#
# Deliberate non-carve-out: `data:` is not allowed even for `image/*`.
# `<a href="data:image/svg+xml,...">` navigates the top frame to an
# attacker SVG that runs script same-origin, which is the exact XSS sink
# this allowlist exists to close.
_SAFE_ANCHOR_SCHEMES: frozenset = frozenset({"http", "https", "mailto"})
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
# Hard cap on URI length to short-circuit pathological inputs. Modern
# browsers truncate URLs well below this; servers commonly cap at 8 KB.
# An anchor URI longer than that is almost certainly hostile or
# malformed, and scanning it codepoint-by-codepoint twice (Python + TS)
# is wasted work.
_MAX_ANCHOR_URI_LEN = 8192
# C0+DEL (0x00 to 0x1F, 0x7F) are stripped from the scheme by some browser URL
# parsers ahead of evaluation, so "java\tscript:..." would unmask. C1 (0x80
# to 0x9F) and the Unicode format marks below cannot un-mask a forbidden
# scheme in modern browsers, but they can visually impersonate the URI when
# the title is rendered, so reject them too.
_DISALLOWED_URI_CODEPOINTS = frozenset(
    list(range(0x00, 0x20))                # C0
    + [0x7F]                              # DEL
    + list(range(0x80, 0xA0))             # C1
    + [0x0085, 0x00A0, 0x2028, 0x2029, 0xFEFF]
    + list(range(0x200B, 0x2010))          # ZWSP/ZWNJ/ZWJ + LRM/RLM
    + list(range(0x202A, 0x202F))          # LRE/RLE/PDF/LRO/RLO
    + list(range(0x2066, 0x2070))          # LRI/RLI/FSI/PDI + deprecated
)


def has_dangerous_text_codepoints(s: str) -> bool:
    """Return True if ``s`` contains any codepoint in the same set
    ``safe_anchor_uri`` rejects (C0/DEL/C1, NEL/NBSP/LS/PS/BOM, ZWSP,
    bidi-override controls). Useful at any boundary that embeds an
    untrusted string into rendered text or prompt prose where a
    line-break, visual-impersonation, or bidi-reorder vector would
    matter.
    """
    return any(ord(ch) in _DISALLOWED_URI_CODEPOINTS for ch in s)


def safe_anchor_uri(uri: str) -> str:
    """Return ``uri`` when its scheme is in the chat anchor allowlist.

    Returns an empty string for anything else. Callers should treat the
    empty return as "do not render as an anchor."
    """
    if not isinstance(uri, str):
        return ""
    if len(uri) > _MAX_ANCHOR_URI_LEN:
        return ""
    # Scan the original input — str.strip() treats NEL, NBSP, LS, PS, and
    # other unicode whitespace as trimmable, so checking after stripping
    # would let those codepoints slip past as a trailing edge.
    if has_dangerous_text_codepoints(uri):
        return ""
    stripped = uri.strip()
    if not stripped:
        return ""
    match = _SCHEME_RE.match(stripped)
    if not match:
        return ""
    if match.group(1).lower() not in _SAFE_ANCHOR_SCHEMES:
        return ""
    return stripped


# Launcher-tile IDs as used by the `disabled_coding_agent_launchers` traitlet
# and `NBI_ENABLED_CODING_AGENT_LAUNCHERS` env var. Match the kebab-case the
# capabilities response already uses for `*_cli_available` keys, but with
# `github-copilot-cli` (not `github-copilot`) so the ID can't collide with
# the `disabled_providers` value for the Copilot LLM provider — those are
# different surfaces and should never share a string identifier.
VALID_CODING_AGENT_LAUNCHERS: tuple[str, ...] = (
    "claude-code",
    "opencode",
    "pi",
    "github-copilot-cli",
    "codex",
)


def is_coding_agent_launcher_enabled_in_env(launcher_id: str) -> bool:
    enabled = os.environ.get('NBI_ENABLED_CODING_AGENT_LAUNCHERS', '')
    return launcher_id in (token.strip() for token in enabled.split(','))


def validate_coding_agent_launcher_ids(disabled) -> None:
    """Raise ValueError when ``disabled`` (the traitlet value) contains an
    unknown launcher ID. Empty / None pass silently.

    Pulled out of ``extension.py`` so tests can exercise the real validator
    rather than re-implementing it inline. Loud-fail-on-typo follows the
    same pattern as ``_resolve_bool_with_env`` for admin gates: a silent
    no-op would let a misconfigured policy ship to production with the tile
    still visible.
    """
    unknown = [
        launcher_id
        for launcher_id in (disabled or [])
        if launcher_id not in VALID_CODING_AGENT_LAUNCHERS
    ]
    if unknown:
        raise ValueError(
            f"Unknown coding-agent launcher ID(s) in "
            f"disabled_coding_agent_launchers: {unknown!r}; "
            f"valid IDs are {VALID_CODING_AGENT_LAUNCHERS}"
        )


def compute_effective_disabled_launchers(disabled, allow_enabling_with_env: bool) -> list:
    """Combine the admin denylist with the per-pod re-enable env var.

    The denylist (``disabled_coding_agent_launchers``) is the floor; an
    entry leaves the effective set only when both
    ``allow_enabling_coding_agent_launchers_with_env`` is True and the
    launcher ID appears in ``NBI_ENABLED_CODING_AGENT_LAUNCHERS``. The
    frontend gets the resulting list and hides matching tiles.
    """
    return [
        launcher_id
        for launcher_id in (disabled or [])
        if not (
            allow_enabling_with_env
            and is_coding_agent_launcher_enabled_in_env(launcher_id)
        )
    ]


# Env-var name substrings that indicate the value is sensitive. The shell
# tools (`execute_command`, `run_command_in_embedded_terminal`) return raw
# stdout/stderr to chat history, so a verbose command like `env`, a
# misbehaving binary that dumps env on error, or `git -c http.extraHeader`
# in trace mode will surface the user's own GITHUB_TOKEN, ANTHROPIC_API_KEY,
# and similar into the chat transcript (and through to the LLM provider).
# Match is case-insensitive substring; values shorter than the floor are
# skipped so a benign one-character env doesn't trigger spurious redaction.
_SECRET_ENV_NAME_PATTERNS: tuple[str, ...] = (
    "TOKEN",
    "PASSWORD",
    "PASSPHRASE",
    "PASSWD",
    "SECRET",
    "API_KEY",
    "APIKEY",
    "PRIVATE_KEY",
    "CREDENTIAL",
    "AUTH",
    "OAUTH",
    "BEARER",
    "COOKIE",
    "JWT",
    "DSN",
    "ACCESS_KEY",  # catches AWS_ACCESS_KEY_ID without the broad bare "KEY"
)
_SECRET_VALUE_MIN_LEN = 8


def _replace_values(text: str, values, *, min_len: int = _SECRET_VALUE_MIN_LEN) -> str:
    """Replace each value's literal occurrences in `text` with `<redacted>`.

    Shared primitive used by both `redact_env_secrets` (process-env scan)
    and ``_claude_cli._scrub_env_overrides`` (call-site env overrides).
    Skips values shorter than ``min_len`` so a short benign value can't
    trigger spurious redaction of unrelated output. Empty `text` and
    empty `values` are no-ops.
    """
    if not text or not values:
        return text
    out = text
    for value in values:
        if value and len(value) >= min_len:
            out = out.replace(value, "<redacted>")
    return out

# Well-known credential prefixes. If a command output contains a string
# starting with one of these, redact through the next whitespace boundary
# even if the value isn't in env. Catches base64 / URL-encoded / derived
# forms where the literal env value never appears (e.g. `curl -u user:$TOK`
# emits `Authorization: Basic <b64(user:tok)>` -- the env-value scan misses
# it). Tokens picked from public provider docs; conservative entropy floor.
_SECRET_VALUE_PREFIXES: tuple[str, ...] = (
    "ghp_",   # GitHub personal access token
    "gho_",   # GitHub OAuth token
    "ghs_",   # GitHub server-to-server
    "ghu_",   # GitHub user-to-server
    "github_pat_",
    "sk-ant-",  # Anthropic
    "sk-",      # OpenAI / generic
    "xoxb-",    # Slack bot
    "xoxp-",    # Slack user
    "xoxa-",    # Slack workspace
    "AKIA",     # AWS access key id
    "ASIA",     # AWS temporary access key id
)
_PREFIX_VALUE_MIN_LEN = 20  # short enough to catch real tokens, long enough to avoid `sk-` false positives


def _looks_like_secret_env_name(name: str) -> bool:
    upper = name.upper()
    return any(pat in upper for pat in _SECRET_ENV_NAME_PATTERNS)


_TOKEN_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(" + "|".join(re.escape(p) for p in _SECRET_VALUE_PREFIXES) + r")[A-Za-z0-9_\-]+"
)


def redact_env_secrets(text: str) -> str:
    """Replace any process-env values that look like secrets with
    ``<redacted>``. Defense in depth for the shell-execute tools, which
    return raw stdout/stderr to chat. A verbose command (``env``,
    ``printenv``, ``git`` with credential-helper tracing) would otherwise
    paste the user's GITHUB_TOKEN / ANTHROPIC_API_KEY / etc. into chat
    history.

    Conservative shape: only env vars whose NAME contains one of the
    sensitive substrings (TOKEN, SECRET, API_KEY, OAUTH, etc.) have their
    VALUES redacted. The value-length floor avoids redacting incidental
    short strings (e.g. a 3-char DEV_TOKEN) that happen to appear
    elsewhere in tool output.

    Secondary pass: any token that begins with a well-known credential
    prefix (``ghp_``, ``sk-ant-``, ``xoxb-``, ``AKIA`` ...) is redacted
    even if the literal env value never appears in the output. Catches
    derived forms like base64-encoded basic-auth where the raw token is
    embedded inside another encoding.

    Known gaps the helper does NOT close:
      - Partial-value leaks: if the output truncates a token
        (``ghp_super…``), the prefix-match path catches it but only when
        the prefix is on the known-form list.
      - Encodings other than the prefix list (URL-encoded, hex-derived
        HMACs computed from the secret): out of scope, addressed at a
        higher layer.
    """
    if not text:
        return text
    # Admin opt-out: a sophisticated user debugging credential helpers may
    # need raw output. Off by default so the redaction stays load-bearing
    # in normal use.
    if os.environ.get("NBI_DISABLE_OUTPUT_SCRUB", "").strip().lower() in ("1", "true", "yes", "on"):
        return text
    # Pass 1: redact literal values for sensitive-named env vars. Routes
    # through the shared `_replace_values` primitive so the redaction
    # contract stays consistent with `_claude_cli._scrub_env_overrides`.
    sensitive_values = [
        value
        for name, value in os.environ.items()
        if value and _looks_like_secret_env_name(name)
    ]
    out = _replace_values(text, sensitive_values)
    # Pass 2: redact known-prefix forms. Catches base64/derived shapes
    # plus tokens an upstream tool might emit that aren't in this
    # process's env (e.g. a token argued via CLI flag, not env).
    def _replace_match(match):
        if len(match.group(0)) >= _PREFIX_VALUE_MIN_LEN:
            return "<redacted>"
        return match.group(0)
    out = _TOKEN_PREFIX_RE.sub(_replace_match, out)
    return out

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
