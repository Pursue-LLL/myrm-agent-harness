"""Stable integration hooks for product consumers (server, desktop).

Re-exports session, skill-agent context, memory extraction, and bash registry
entry points so consumers never import private ``agent._*`` modules directly.
"""

from __future__ import annotations

from myrm_agent_harness.agent._internals.memory_extraction import (
    create_extraction_llm_func,
    persist_extracted_memories,
)
from myrm_agent_harness.agent._skill_agent_context import (
    get_memory_manager,
    invalidate_permissions,
    set_permission_invalidation_callback,
)
from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    get_background_registry,
)
from myrm_agent_harness.agent.middlewares._session_context import (
    get_event_logger,
    get_terminal_errors,
    set_approval_user_id,
)

__all__ = [
    "create_extraction_llm_func",
    "get_background_registry",
    "get_event_logger",
    "get_memory_manager",
    "get_terminal_errors",
    "invalidate_permissions",
    "persist_extracted_memories",
    "set_approval_user_id",
    "set_permission_invalidation_callback",
]
