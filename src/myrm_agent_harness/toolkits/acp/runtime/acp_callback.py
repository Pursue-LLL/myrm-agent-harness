"""ACP callback handler for the AcpRuntime backend.

Implements the acp.Client callback interface: streams RuntimeEvent instances
through an asyncio.Queue for real-time consumption by AcpRuntime._do_run_turn.
Also handles permission requests and file read/write with path safety checks.

[INPUT]
- toolkits.acp.types::PermissionDecision, RuntimeConfig, RuntimeEvent (POS: ACP runtime type definitions layer. Provides all ACP-related core abstractions and data structures, serving as the foundation for the entire ACP module.)
- toolkits.acp.event_bus::EventBus (POS: ACP event bus layer. Provides decoupled event dispatch mechanism for the Runtime system with session isolation and type filtering.)
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: Workspace path resolver with intelligent auto-detection.)

[OUTPUT]
- AcpCallbackHandler: class — Acp Callback Handler

[POS]
ACP callback handler for the AcpRuntime backend.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from myrm_agent_harness.toolkits.acp.event_bus import EventBus
from myrm_agent_harness.toolkits.acp.types import (
    PermissionDecision,
    RuntimeConfig,
    RuntimeEvent,
    RuntimeEventType,
    create_event,
    create_permission_request,
)

logger = logging.getLogger(__name__)
_PERMISSION_REQUEST_TIMEOUT_SECONDS = 30.0


def _resolve_safe_path(path_str: str, cwd: str) -> Path | None:
    """Resolve path within cwd, returning None if outside."""
    try:
        candidate = Path(path_str)
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        resolved = candidate.resolve()
        cwd_resolved = Path(cwd).resolve()
        if resolved == cwd_resolved or str(resolved).startswith(str(cwd_resolved) + os.sep):
            return resolved
        return None
    except (ValueError, OSError):
        return None


def _get_attr(obj: object, *keys: str) -> object | None:
    """Extract an attribute from an object or dict by trying multiple keys."""
    for key in keys:
        if isinstance(obj, dict):
            val = obj.get(key)
        else:
            val = getattr(obj, key, None)
        if val is not None:
            return val
    return None


def _extract_text_content(content: object) -> str | None:
    """Extract text from an ACP content block."""
    if content is None:
        return None
    content_type = _get_attr(content, "type")
    if content_type == "text":
        text = _get_attr(content, "text")
        return str(text) if text is not None else None
    return None


def _find_option(options: list[object], kinds: tuple[str, ...]) -> str | None:
    """Find the first option matching any of the given kinds."""
    for opt in options:
        opt_dict = opt if isinstance(opt, dict) else (opt.model_dump() if hasattr(opt, "model_dump") else {})
        if opt_dict.get("kind") in kinds:
            return str(opt_dict.get("optionId", ""))
    return None


def _select_outcome(option_id: str) -> dict[str, object]:
    return {"outcome": {"outcome": "selected", "optionId": option_id}}


def _cancel_outcome() -> dict[str, object]:
    return {"outcome": {"outcome": "cancelled"}}


def _reject_or_cancel(option_list: list[object]) -> dict[str, object]:
    reject = _find_option(option_list, ("reject_once", "reject_always"))
    if reject:
        return _select_outcome(reject)
    return _cancel_outcome()


def _auto_allow(option_list: list[object]) -> dict[str, object]:
    allow = _find_option(option_list, ("allow_once", "allow_always"))
    if allow:
        return _select_outcome(allow)
    return _cancel_outcome()


class AcpCallbackHandler:
    """Implements acp.Client callbacks for the ACP runtime.

    Streams RuntimeEvent instances through an asyncio.Queue for real-time
    consumption by AcpRuntime._do_run_turn. Also collects full response text
    for truncation and final assembly.
    """

    def __init__(
        self,
        config: RuntimeConfig,
        session_id: str,
        *,
        event_bus: EventBus | None = None,
        permission_request_timeout: float = _PERMISSION_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver

        self._config = config
        self._session_id = session_id
        self._cwd = config.cwd or str(WorkspacePathResolver.resolve_workspace_root())
        self._event_bus = event_bus
        self._permission_request_timeout = permission_request_timeout
        self._text_parts: list[str] = []
        self._event_queue: asyncio.Queue[RuntimeEvent | None] = asyncio.Queue()

    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        self._session_id = value

    @property
    def event_queue(self) -> asyncio.Queue[RuntimeEvent | None]:
        return self._event_queue

    @property
    def response_text(self) -> str:
        return "".join(self._text_parts)

    def reset(self) -> None:
        self._text_parts.clear()
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def mark_done(self, stop_reason: str) -> None:
        """Signal that the prompt has completed. Pushes a DONE event + sentinel."""
        self._event_queue.put_nowait(create_event(RuntimeEventType.DONE, self._session_id, stop_reason=stop_reason))
        self._event_queue.put_nowait(None)

    def on_connect(self, conn: object) -> None:
        pass

    def _push_event(self, event: RuntimeEvent) -> None:
        """Push a RuntimeEvent to the queue for real-time consumption."""
        self._event_queue.put_nowait(event)

    async def session_update(
        self,
        session_id: str,
        update: object,
        **kwargs: object,
    ) -> None:
        """Convert session_update events to RuntimeEvents and push to queue."""
        update_type = _get_attr(update, "session_update", "sessionUpdate")
        content = _get_attr(update, "content")

        if update_type == "agent_message_chunk":
            text = _extract_text_content(content)
            if text:
                self._text_parts.append(text)
                self._push_event(create_event(RuntimeEventType.TEXT_DELTA, self._session_id, content=text))

        elif update_type == "tool_call":
            title = str(_get_attr(update, "title") or "unknown")
            status = str(_get_attr(update, "status") or "")
            self._text_parts.append(f"\n[tool: {title} ({status})]\n")
            tool_call_id = str(_get_attr(update, "tool_call_id", "toolCallId") or title)
            self._push_event(
                create_event(
                    RuntimeEventType.TOOL_START,
                    self._session_id,
                    tool_name=title,
                    tool_call_id=tool_call_id,
                )
            )

        elif update_type == "tool_call_update":
            status = str(_get_attr(update, "status") or "")
            if status in ("completed", "failed"):
                tool_id = str(_get_attr(update, "tool_call_id", "toolCallId") or "")
                self._text_parts.append(f"[tool update: {tool_id} -> {status}]\n")
                output = str(_get_attr(update, "content") or "")
                self._push_event(
                    create_event(
                        RuntimeEventType.TOOL_RESULT,
                        self._session_id,
                        tool_call_id=tool_id,
                        output=output,
                        is_error=(status == "failed"),
                    )
                )

        elif update_type == "agent_thought_chunk":
            text = _extract_text_content(content)
            if text:
                self._text_parts.append(text)
                self._push_event(create_event(RuntimeEventType.REASONING_DELTA, self._session_id, content=text))

    async def request_permission(
        self,
        options: list[object],
        session_id: str,
        tool_call: object,
        **kwargs: object,
    ) -> dict[str, object]:
        """Handle permission requests based on configured permission_mode."""
        option_list = options if isinstance(options, list) else []
        tool_dict = (
            tool_call
            if isinstance(tool_call, dict)
            else (tool_call.model_dump() if hasattr(tool_call, "model_dump") else {})
        )
        tool_name = str(tool_dict.get("title") or tool_dict.get("name") or "unknown")
        tool_input = {
            key: value for key, value in tool_dict.items() if key in ("command", "path", "input", "arguments", "files")
        }

        mode = self._config.permission_mode
        if mode == "safe":
            return self._handle_safe_mode(tool_name, option_list)
        if mode == "ask":
            return await self._handle_ask_mode(session_id, tool_name, tool_input, option_list)
        if mode == "bypass":
            return _select_outcome("allow_always")
        return _auto_allow(option_list)

    def _handle_safe_mode(self, tool_name: str, option_list: list[object]) -> dict[str, object]:
        """Safe mode: allow read operations, reject everything else."""
        is_read_op = any(kw in tool_name.lower() for kw in ("read", "search", "list", "glob"))
        if is_read_op:
            allow = _find_option(option_list, ("allow_once", "allow_always"))
            if allow:
                return _select_outcome(allow)
        return _reject_or_cancel(option_list)

    async def _handle_ask_mode(
        self,
        session_id: str,
        tool_name: str,
        tool_input: dict[str, object],
        option_list: list[object],
    ) -> dict[str, object]:
        """Ask mode: emit permission request event and await external decision."""
        if self._event_bus is None:
            logger.warning(
                "permission_request_ignored_ask_no_bus session_id=%s tool=%s",
                self._session_id,
                tool_name,
            )
            return _reject_or_cancel(option_list)

        request_event, decision_future = create_permission_request(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
        )
        request_event.data["options"] = option_list
        await self._event_bus.emit(request_event)

        try:
            decision = await asyncio.wait_for(
                decision_future,
                timeout=self._permission_request_timeout,
            )
        except (TimeoutError, RuntimeError):
            logger.warning("permission_request_timeout session_id=%s tool=%s", session_id, tool_name)
            decision = PermissionDecision.DENY_ONCE

        selected_option = self._decision_to_option(option_list, decision)
        if selected_option is None:
            logger.warning(
                "permission_request_invalid session_id=%s tool=%s decision=%s",
                session_id,
                tool_name,
                decision,
            )
            return _cancel_outcome()
        return _select_outcome(selected_option)

    @staticmethod
    def _decision_to_option(
        option_list: list[object],
        decision: PermissionDecision,
    ) -> str | None:
        deny_kinds = ("reject_once", "reject_always")

        if decision == PermissionDecision.ALLOW_ALWAYS:
            return _find_option(option_list, ("allow_always", "allow_once"))
        if decision == PermissionDecision.ALLOW_ONCE:
            return _find_option(option_list, ("allow_once", "allow_always"))
        if decision == PermissionDecision.DENY_ALWAYS:
            return _find_option(option_list, ("reject_always", "reject_once"))

        return _find_option(option_list, deny_kinds)

    async def read_text_file(
        self,
        path: str,
        session_id: str,
        limit: int | None = None,
        line: int | None = None,
        **kwargs: object,
    ) -> dict[str, str]:
        """Read a file within the configured cwd (with path safety check)."""
        resolved = _resolve_safe_path(path, self._cwd)
        if resolved is None:
            return {"content": f"[error] Path '{path}' is outside working directory"}
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
            if line is not None and limit is not None:
                lines = content.splitlines(keepends=True)
                content = "".join(lines[max(0, line - 1) : line - 1 + limit])
            return {"content": content}
        except OSError as exc:
            return {"content": f"[error] Cannot read file: {exc}"}

    async def write_text_file(
        self,
        content: str,
        path: str,
        session_id: str,
        **kwargs: object,
    ) -> dict[str, bool] | None:
        """Write a file within the configured cwd (permission_mode gated)."""
        if self._config.permission_mode in ("safe",):
            logger.warning("write_text_file_denied path=%s", path)
            return None

        resolved = _resolve_safe_path(path, self._cwd)
        if resolved is None:
            logger.warning("write_text_file_outside_cwd path=%s", path)
            return None
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return {"success": True}
        except OSError as exc:
            logger.error("write_text_file_failed path=%s error=%s", path, exc)
            return None
