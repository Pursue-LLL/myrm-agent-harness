"""Shared types, queue envelopes, and error classification helpers for MCPSessionActor.

[INPUT]
- mcp.types (POS: MCP SDK notification and elicitation types)

[OUTPUT]
- MCPElicitationHandler, MCPActorResolver: type aliases
- _TransientStartError, _ServeOutcome, _ToolCall, _ResourceRead, _SHUTDOWN, _REFRESH_SIGNAL
- _is_auth_error, _describe_error, _extract_instructions
- build_elicitation_callback, build_notification_handler, read_mcp_resource

[POS]
Internal support module for ``session_actor.py``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session_actor import MCPSessionActor

logger = logging.getLogger(__name__)

# Business-layer elicitation callback: async (server_name, message, schema) -> decision.
MCPElicitationHandler = Callable[[str, str, dict[str, object]], Awaitable[str]]
MCPActorResolver = Callable[[], Awaitable["MCPSessionActor | None"]]


class _TransientStartError(Exception):
    """Internal marker: a retryable session-establishment failure."""


class _ServeOutcome(Enum):
    """How the serve loop ended, telling the owner task what to do next."""

    SHUTDOWN = "shutdown"
    RECONNECT = "reconnect"


@dataclass(slots=True)
class _ToolCall:
    """A queued tool invocation awaiting execution on the warm session."""

    tool_name: str
    params: dict[str, object]
    future: asyncio.Future[object]


@dataclass(slots=True)
class _ResourceRead:
    """A queued resource read awaiting execution on the warm session."""

    uri: str
    future: asyncio.Future[object]


_SHUTDOWN = object()
_REFRESH_SIGNAL = object()

_AUTH_ERROR_PATTERN = re.compile(
    r"\b401\b|unauthorized|invalid_token|token.?expired|unauthenticated",
    re.IGNORECASE,
)


def _is_auth_error(detail: str) -> bool:
    """Heuristic: return True if the error description indicates an auth/token failure."""
    return _AUTH_ERROR_PATTERN.search(detail) is not None


def _describe_error(exc: Exception) -> str:
    """One-line cause for logs and start errors (transient marker stays terse)."""
    if isinstance(exc, _TransientStartError):
        return str(exc)
    if isinstance(exc, BaseExceptionGroup):
        sub_causes = "; ".join(f"{type(e).__name__}: {e}" for e in exc.exceptions)
        return f"{type(exc).__name__}: {exc} [nested: {sub_causes}]"
    return f"{type(exc).__name__}: {exc}"


def _extract_instructions(client_or_result: object) -> str | None:
    """Pull server instructions from an MCP Client or result object."""
    instructions = getattr(client_or_result, "instructions", None)
    if not instructions:
        server_info = getattr(client_or_result, "server_info", None)
        if server_info is not None:
            instructions = getattr(server_info, "instructions", None)
    return instructions if isinstance(instructions, str) else None


def build_elicitation_callback(
    server_name: str,
    handler: MCPElicitationHandler | None,
    timeout_getter: Callable[[], float],
) -> object | None:
    """Build an ``elicitation_callback`` for ``mcp.ClientSession``."""
    if handler is None:
        return None

    async def _elicitation_callback(context: object, params: object) -> object:
        from mcp.types import ElicitResult

        mode = getattr(params, "mode", "form")
        if mode == "url":
            logger.info(
                "MCP server '%s' requested url-mode elicitation; declining (not supported)",
                server_name,
            )
            return ElicitResult(action="decline")

        message = getattr(params, "message", "") or f"MCP server '{server_name}' requests confirmation"
        schema = getattr(params, "requested_schema", None) or {}
        timeout_val = timeout_getter()

        try:
            decision = await asyncio.wait_for(
                handler(server_name, message, schema),
                timeout=timeout_val,
            )
        except TimeoutError:
            logger.warning(
                "MCP server '%s' elicitation timed out after %ds",
                server_name,
                int(timeout_val),
            )
            return ElicitResult(action="cancel")
        except Exception as exc:
            logger.error(
                "MCP server '%s' elicitation handler failed: %s",
                server_name,
                exc,
                exc_info=True,
            )
            return ElicitResult(action="decline")

        if decision == "accept":
            return ElicitResult(action="accept")
        if decision == "decline":
            return ElicitResult(action="decline")
        if decision == "cancel":
            return ElicitResult(action="cancel")
        logger.warning(
            "MCP server '%s' elicitation handler returned unexpected value: %r; declining",
            server_name,
            decision,
        )
        return ElicitResult(action="decline")

    return _elicitation_callback


def build_notification_handler(
    server_name: str,
    queue: asyncio.Queue[_ToolCall | object],
) -> Callable[[object], Awaitable[None]] | None:
    """Build a ``message_handler`` for ``mcp.ClientSession``."""
    try:
        from mcp.types import (
            PromptListChangedNotification,
            ResourceListChangedNotification,
            ToolListChangedNotification,
        )
    except ImportError:
        logger.debug("MCP SDK notification types unavailable; dynamic tool discovery disabled")
        return None

    async def _handler(message: object) -> None:
        try:
            if isinstance(message, Exception):
                return
            if isinstance(message, ToolListChangedNotification):
                logger.info(
                    "MCP server '%s': received tools/list_changed",
                    server_name,
                )
                queue.put_nowait(_REFRESH_SIGNAL)
            elif isinstance(message, PromptListChangedNotification):
                logger.debug(
                    "MCP server '%s': prompts/list_changed (ignored)",
                    server_name,
                )
            elif isinstance(message, ResourceListChangedNotification):
                logger.debug(
                    "MCP server '%s': resources/list_changed (ignored)",
                    server_name,
                )
        except Exception:
            logger.exception("Error in MCP notification handler for '%s'", server_name)

    return _handler


async def read_mcp_resource(
    session: object,
    uri: str,
    connect_timeout: float,
) -> bytes:
    """Read a resource from the MCP server via the active session."""
    try:
        from mcp.types import ReadResourceResult
    except ImportError as exc:
        raise RuntimeError("MCP SDK not available for resource reading") from exc

    async with asyncio.timeout(connect_timeout):
        result: ReadResourceResult = await session.read_resource(uri)  # type: ignore[attr-defined]
    if not result.contents:
        raise RuntimeError(f"MCP resource '{uri}' returned empty content")
    content = result.contents[0]
    if hasattr(content, "blob") and content.blob:
        import base64

        return base64.b64decode(content.blob)
    if hasattr(content, "text") and content.text:
        return content.text.encode("utf-8")
    raise RuntimeError(f"MCP resource '{uri}' has no text or blob content")
