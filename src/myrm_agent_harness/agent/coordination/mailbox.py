"""In-memory + JSONL teammate mailbox for sibling subagent messaging.

[INPUT]
- coordination.types::TeammateMessage (POS: P2P message payload dataclass)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: Agent SSE push from tools)

[OUTPUT]
- TeammateMailbox: send, drain, roster, sliding-window rate limit, JSONL persistence
- emit_teammate_message_sse: immediate GUI event on successful send
- drain_teammate_messages_for_task: subagent turn-boundary injection hook

[POS]
Session-scoped sibling subagent mailbox. Keeps P2P traffic out of parent context.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .types import TeammateMessage, TeammateSendResult

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

_MAILBOX_CACHE: dict[str, TeammateMailbox] = {}
_LAST_DRAINED_BY_TASK: dict[str, list[TeammateMessage]] = {}
_RATE_LIMIT_PER_SENDER = 30
_RATE_LIMIT_WINDOW_SEC = 60.0
_MAX_JSONL_LINES = 1000
_RATE_LIMIT_ERROR = "Teammate mailbox rate limit exceeded: max 30 messages per sender within 60 seconds."


@dataclass(frozen=True, slots=True)
class DrainResult:
    messages: list[TeammateMessage]


class TeammateMailbox:
    """Session-scoped mailbox with optional workspace JSONL persistence."""

    def __init__(self, session_id: str, workspace_path: str | None) -> None:
        self.session_id = session_id
        self.workspace_path = workspace_path
        self._inboxes: dict[str, deque[TeammateMessage]] = {}
        self._sender_send_times: dict[str, deque[float]] = {}
        self._active_roster: dict[str, str] = {}
        self._persist_path: Path | None = None
        if workspace_path:
            root = Path(workspace_path)
            root.mkdir(parents=True, exist_ok=True)
            self._persist_path = root / f"teammate_mailbox_{session_id}.jsonl"

    def register_active(self, task_id: str, agent_type: str) -> None:
        self._active_roster[task_id] = agent_type

    def unregister_active(self, task_id: str) -> None:
        self._active_roster.pop(task_id, None)

    def list_active_roster(self, exclude_task_id: str | None = None) -> list[dict[str, str]]:
        return [
            {"task_id": task_id, "agent_type": agent_type}
            for task_id, agent_type in self._active_roster.items()
            if task_id != exclude_task_id
        ]

    def _check_rate_limit(self, sender_task_id: str) -> bool:
        """Sliding window: at most 30 sends per sender within 60 seconds."""
        now = time.time()
        window_start = now - _RATE_LIMIT_WINDOW_SEC
        timestamps = self._sender_send_times.setdefault(sender_task_id, deque())
        while timestamps and timestamps[0] <= window_start:
            timestamps.popleft()
        if len(timestamps) >= _RATE_LIMIT_PER_SENDER:
            return False
        timestamps.append(now)
        return True

    async def send(self, message: TeammateMessage) -> TeammateSendResult:
        return self.send_sync(message)

    def send_sync(self, message: TeammateMessage) -> TeammateSendResult:
        if not self._check_rate_limit(message.from_task_id):
            logger.warning(
                "Teammate mailbox rate limit exceeded: sender=%s session=%s",
                message.from_task_id,
                self.session_id,
            )
            return TeammateSendResult(accepted=False, error=_RATE_LIMIT_ERROR)
        inbox = self._inboxes.setdefault(message.to_task_id, deque())
        inbox.append(message)
        self._persist(message)
        return TeammateSendResult(accepted=True)

    def drain_unread_sync(self, to_task_id: str) -> DrainResult:
        inbox = self._inboxes.get(to_task_id)
        if not inbox:
            return DrainResult(messages=[])
        messages = list(inbox)
        inbox.clear()
        return DrainResult(messages=messages)

    def _persist(self, message: TeammateMessage) -> None:
        if self._persist_path is None:
            return
        try:
            with self._persist_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
            self._trim_persist_file_if_needed()
        except OSError as exc:
            logger.warning("Failed to persist teammate message: %s", exc)

    def _trim_persist_file_if_needed(self) -> None:
        if self._persist_path is None or not self._persist_path.is_file():
            return
        try:
            lines = self._persist_path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= _MAX_JSONL_LINES:
                return
            tail = lines[-_MAX_JSONL_LINES:]
            self._persist_path.write_text(
                "\n".join(tail) + ("\n" if tail else ""),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to trim teammate mailbox JSONL: %s", exc)


async def register_active_teammate(
    session_id: str,
    workspace_path: str | None,
    task_id: str,
    agent_type: str,
) -> None:
    """Register a spawned subagent on the session roster."""
    if not session_id or not task_id:
        return
    mailbox = await get_teammate_mailbox(session_id, workspace_path)
    mailbox.register_active(task_id, agent_type)


def unregister_active_teammate(session_id: str, task_id: str) -> None:
    """Remove a completed subagent from the session roster."""
    if not session_id or not task_id:
        return
    mailbox = _MAILBOX_CACHE.get(session_id)
    if mailbox is not None:
        mailbox.unregister_active(task_id)


async def get_teammate_mailbox(
    session_id: str,
    workspace_path: str | None,
) -> TeammateMailbox:
    cached = _MAILBOX_CACHE.get(session_id)
    if cached is not None:
        return cached
    mailbox = TeammateMailbox(session_id, workspace_path)
    _MAILBOX_CACHE[session_id] = mailbox
    return mailbox


def format_teammate_injection(messages: Iterable[TeammateMessage]) -> str | None:
    items = list(messages)
    if not items:
        return None
    lines = ["<teammate-message>"]
    for msg in items:
        lines.append(f"From {msg.from_task_id} ({msg.from_agent_type}) to {msg.to_task_id}: {msg.body}")
    lines.append("</teammate-message>")
    return "\n".join(lines)


def format_roster_prompt(roster: list[dict[str, str]]) -> str | None:
    if not roster:
        return None
    lines = ["<active_teammates>"]
    for entry in roster:
        lines.append(f"- {entry.get('task_id')}: {entry.get('agent_type')}")
    lines.append("</active_teammates>")
    return "\n".join(lines)


def list_teammate_history(
    session_id: str,
    workspace_path: str | None,
    limit: int = 200,
) -> list[dict[str, object]]:
    if not workspace_path:
        return []
    path = Path(workspace_path) / f"teammate_mailbox_{session_id}.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, object]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
            if len(rows) >= limit:
                break
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read teammate history from %s: %s", path, exc)
    return rows


def get_last_drained_messages(task_id: str) -> list[TeammateMessage]:
    """Messages from the most recent drain for stream UI events."""
    return list(_LAST_DRAINED_BY_TASK.get(task_id, []))


async def emit_teammate_message_sse(message: TeammateMessage) -> None:
    """Push teammate_message to the active agent SSE stream (M1: send-then-see)."""
    from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

    sink = get_tool_progress_sink()
    if sink is None:
        return
    try:
        await sink.emit(
            {
                "type": "teammate_message",
                "data": {
                    **message.to_dict(),
                    "chat_id": message.session_id,
                },
            }
        )
    except Exception as exc:
        logger.warning("Failed to emit teammate_message SSE: %s", exc)


def drain_teammate_messages_for_task(session_id: str, task_id: str) -> str | None:
    """Sync drain hook for StreamExecutor (subagent turn boundary)."""
    if not session_id or not task_id:
        return None
    mailbox = _MAILBOX_CACHE.get(session_id)
    if mailbox is None:
        return None
    result = mailbox.drain_unread_sync(task_id)
    if result.messages:
        _LAST_DRAINED_BY_TASK[task_id] = list(result.messages)
    return format_teammate_injection(result.messages)


def group_history_by_task(
    history: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    seen: set[str] = set()
    for row in history:
        message_id = row.get("message_id")
        if isinstance(message_id, str):
            if message_id in seen:
                continue
            seen.add(message_id)
        for key in ("from_task_id", "to_task_id"):
            task_id = row.get(key)
            if isinstance(task_id, str) and task_id:
                bucket = grouped.setdefault(task_id, [])
                bucket.append(row)
                if len(bucket) > 20:
                    del bucket[:-20]
    return grouped
