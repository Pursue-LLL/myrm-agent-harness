"""Factory assembling the three agent memory tools.

[INPUT]
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager)
- toolkits.memory.config::RecallMode (POS: tool visibility mode)
- toolkits.memory.agent_surface._memory_agent_tool_descriptions (POS: LLM-visible memory tool description SSOT)
- toolkits.memory.agent_surface.memory_search_policy (POS: corpus ACL and optional wiki/sessions backends)

[OUTPUT]
- create_memory_tools: Create memory_search_tool, memory_save_tool, memory_manage_tool.

[POS]
Framework-level: depends only on MemoryManager (protocol-based); the server binds wiki and
conversation providers through MemorySearchBackends.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.agent_surface._memory_agent_tool_descriptions import (
    build_memory_save_tool_description,
    build_memory_search_tool_description,
    resolve_memory_manage_tool_description,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools.manage_tool import build_memory_manage_tool
from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools.save_tool import build_memory_save_tool
from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools.search_tool import build_memory_search_tool
from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
    MemorySearchBackends,
    MemorySearchPolicy,
)
from myrm_agent_harness.toolkits.memory.config import RecallMode
from myrm_agent_harness.toolkits.memory.manager import MemoryManager


def create_memory_tools(
    manager: MemoryManager,
    recall_mode: RecallMode = RecallMode.HYBRID,
    *,
    search_policy: MemorySearchPolicy | None = None,
    search_backends: MemorySearchBackends | None = None,
    description_locale: str | None = None,
) -> list[object]:
    """Create memory tools for the user bound to the manager.

    Args:
        manager: MemoryManager instance (user_id is set at construction).
            If ``manager.approval_required`` is True, memory_save will
            route through the approval queue automatically.
        recall_mode: Controls tool visibility.
            HYBRID (default): all tools exposed.
            CONTEXT: no tools (context injection only, for API/headless).
            TOOLS: all tools exposed (no context injection handled here).
        search_policy: Runtime ACL for memory_search_tool corpus selection.
        search_backends: Optional wiki/sessions providers bound by server.
        description_locale: BCP-47 locale for LLM-facing tool descriptions (default English).
    """
    if recall_mode == RecallMode.CONTEXT:
        return []

    policy = search_policy or MemorySearchPolicy()
    backends = search_backends or MemorySearchBackends()

    return [
        build_memory_search_tool(
            manager,
            policy,
            backends,
            description=build_memory_search_tool_description(policy, locale=description_locale),
        ),
        build_memory_save_tool(
            manager,
            policy,
            description=build_memory_save_tool_description(
                policy,
                approval_required=manager.approval_required,
                locale=description_locale,
            ),
        ),
        build_memory_manage_tool(
            manager,
            description=resolve_memory_manage_tool_description(description_locale),
        ),
    ]
