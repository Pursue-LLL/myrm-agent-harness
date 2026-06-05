"""PTC builtin: cross-call session key-value store.

Provides ``tools.session_store(key, value)`` / ``tools.session_load(key)`` /
``tools.session_keys()`` for PTC scripts. Python execution is stateless across
``bash_code_execute_tool`` invocations: without this module, LLMs that want to
pass intermediate results across turns must re-emit them as text (token cost)
or re-call upstream tools. Session storage keeps the prompt cache lean.

Design:
- Storage lives at ``<workspace_root>/.session_store/<session_id>.json`` so it
  is naturally isolated per chat (chat_id == session_id), survives container
  restarts, and is portable to SaaS sandboxes (volume-mounted workspaces).
- File access is serialised by an asyncio.Lock per (workspace, session_id)
  pair to avoid TOCTOU corruption under concurrent PTC calls in one chat.
- Values must be JSON-serialisable. Large values (> 256 KiB) are rejected with
  a clear error pointing the LLM to ``ArtifactVault`` (``vault://``) — keeps
  the prompt cache lean and prevents token explosions on subsequent loads.

[INPUT]
- agent.skills.mcp.ipc_proxy::get_ipc_call_context (POS: Session context from IPC dispatch.)

[OUTPUT]
- session_store_handler / session_load_handler / session_keys_handler
- SessionStoreError: Domain error surfaced to LLM via IPC error channel.

[POS]
File-backed session KV store for PTC scripts. Used by BuiltinToolRegistry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

_MAX_VALUE_BYTES: Final[int] = 256 * 1024
_STORE_DIR_NAME: Final[str] = ".session_store"
# Only allow filename-safe session identifiers: letters, digits, dash,
# underscore and dot (but not as the first/only char). Blocks path
# traversal payloads such as ``../../etc`` even when an attacker
# overwrites ``_SESSION_ID`` from inside a PTC script.
_SAFE_SESSION_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_locks: dict[tuple[str, str], asyncio.Lock] = {}


class SessionStoreError(Exception):
    """Raised when a session_store operation fails or violates constraints."""


def _get_lock(workspace_root: str, session_id: str) -> asyncio.Lock:
    key = (workspace_root, session_id)
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def _validate_session_id(session_id: str) -> None:
    if not _SAFE_SESSION_ID_RE.fullmatch(session_id):
        raise SessionStoreError(
            f"session_store: invalid session_id {session_id!r}; must match [A-Za-z0-9][A-Za-z0-9._-]* (max 128 chars)."
        )


def _resolve_store_path() -> tuple[Path, asyncio.Lock]:
    """Resolve the store file path from the current IPC call context.

    Validates ``session_id`` and ensures the resulting path stays under
    ``<workspace_root>/.session_store/`` to defend against path traversal
    attempts ("../../etc") that an attacker could smuggle in via a PTC
    script overwriting the injected ``_SESSION_ID`` constant.
    """
    from myrm_agent_harness.agent.skills.mcp.ipc_proxy import get_ipc_call_context

    ctx = get_ipc_call_context()
    if ctx is None or not ctx.session_id or not ctx.workspace_root:
        raise SessionStoreError("session_store requires session_id and workspace_root in IPC context.")

    _validate_session_id(ctx.session_id)

    workspace_root = Path(ctx.workspace_root).resolve()
    store_dir = (workspace_root / _STORE_DIR_NAME).resolve()
    if not str(store_dir).startswith(str(workspace_root)):
        raise SessionStoreError("session_store: resolved store directory escapes the workspace root.")
    store_dir.mkdir(parents=True, exist_ok=True)

    target = (store_dir / f"{ctx.session_id}.json").resolve()
    if not str(target).startswith(str(store_dir)):
        raise SessionStoreError("session_store: resolved file path escapes the store directory.")
    return target, _get_lock(ctx.workspace_root, ctx.session_id)


async def _read_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
        data = json.loads(raw) if raw else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionStoreError(f"failed to read session store: {exc}") from exc
    if not isinstance(data, dict):
        raise SessionStoreError("session store file is corrupted (not a JSON object).")
    return data


async def _write_store(path: Path, data: dict[str, Any]) -> None:
    try:
        payload = json.dumps(data, ensure_ascii=False)
        await asyncio.to_thread(path.write_text, payload, encoding="utf-8")
    except (OSError, TypeError, ValueError) as exc:
        raise SessionStoreError(f"failed to write session store: {exc}") from exc


async def session_store_handler(params: dict[str, object]) -> None:
    """Persist ``params['value']`` under ``params['key']``.

    Raises SessionStoreError on validation failure; the IPC layer turns it
    into an error response visible to the LLM as ``MCPError``.
    """
    key = params.get("key")
    if not isinstance(key, str) or not key:
        raise SessionStoreError("session_store: 'key' must be a non-empty string.")
    if "value" not in params:
        raise SessionStoreError("session_store: 'value' is required.")
    value = params["value"]

    try:
        serialised = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise SessionStoreError(f"session_store: value for key '{key}' is not JSON-serialisable ({exc}).") from exc

    if len(serialised.encode("utf-8")) > _MAX_VALUE_BYTES:
        raise SessionStoreError(
            f"session_store: value for '{key}' exceeds {_MAX_VALUE_BYTES // 1024} KiB; "
            "write large blobs to a file and store the 'vault://' reference instead."
        )

    path, lock = _resolve_store_path()
    async with lock:
        data = await _read_store(path)
        data[key] = value
        await _write_store(path, data)
    logger.debug("session_store: wrote key=%s (%d bytes)", key, len(serialised))
    return None


async def session_load_handler(params: dict[str, object]) -> object:
    """Return the stored value for ``params['key']`` (``None`` if missing)."""
    key = params.get("key")
    if not isinstance(key, str) or not key:
        raise SessionStoreError("session_load: 'key' must be a non-empty string.")

    path, lock = _resolve_store_path()
    async with lock:
        data = await _read_store(path)
    return data.get(key)


async def session_keys_handler(_params: dict[str, object]) -> list[str]:
    """Return all keys currently present in the session store."""
    path, lock = _resolve_store_path()
    async with lock:
        data = await _read_store(path)
    return sorted(data.keys())


__all__ = [
    "SessionStoreError",
    "session_keys_handler",
    "session_load_handler",
    "session_store_handler",
]
