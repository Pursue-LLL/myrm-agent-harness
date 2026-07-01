"""Stable integration hooks for product consumers (server, desktop).

[INPUT]
- myrm_agent_harness.agent._skill_agent_context (POS: per-agent runtime context registry)
- myrm_agent_harness.agent._internals.memory_extraction (POS: session memory extraction helpers)
- myrm_agent_harness.agent.middlewares._session_context (POS: middleware session ContextVar registry)
- myrm_agent_harness.agent.meta_tools.bash._background_registry (POS: background bash job registry)

[OUTPUT]
- Session, skill-agent, memory-extraction, and bash-registry hook callables for server integration.

[POS]
Public re-export facade. Product code imports hooks here instead of private ``agent._*`` modules.
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
