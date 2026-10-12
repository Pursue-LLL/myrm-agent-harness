"""Per-request scoping for the memory MCP tools.

[INPUT]
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager, TYPE_CHECKING only)

[OUTPUT]
- set/reset/get_request_memory_manager: bind the MemoryManager used by tool handlers for the current request
- set/reset/get_request_wiki_boundary_enabled: bind the wiki document-rejection flag for memory_store

[POS]
ContextVar bindings set by the HTTP layer (e.g. per-token agent scoping) and read by the tool handlers.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

_request_memory_manager: ContextVar[MemoryManager | None] = ContextVar(
    "myrm_mcp_request_memory_manager",
    default=None,
)
_request_wiki_boundary_enabled: ContextVar[bool] = ContextVar(
    "myrm_mcp_request_wiki_boundary_enabled",
    default=False,
)


def set_request_memory_manager(
    manager: MemoryManager | None,
) -> Token[MemoryManager | None]:
    """Bind the MemoryManager used by MCP tool handlers for the current request."""
    return _request_memory_manager.set(manager)


def reset_request_memory_manager(token: Token[MemoryManager | None]) -> None:
    """Restore the previous MemoryManager binding after a request completes."""
    _request_memory_manager.reset(token)


def get_request_memory_manager() -> MemoryManager | None:
    """Return the MemoryManager bound to the current MCP request, if any."""
    return _request_memory_manager.get()


def set_request_wiki_boundary_enabled(enabled: bool) -> Token[bool]:
    """Bind whether wiki document-like payloads should be rejected on memory_store."""
    return _request_wiki_boundary_enabled.set(enabled)


def reset_request_wiki_boundary_enabled(token: Token[bool]) -> None:
    """Restore the previous wiki boundary flag after a request completes."""
    _request_wiki_boundary_enabled.reset(token)


def get_request_wiki_boundary_enabled() -> bool:
    """Return the active wiki boundary flag for the current MCP request."""
    return _request_wiki_boundary_enabled.get()
