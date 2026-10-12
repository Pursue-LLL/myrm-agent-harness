"""memory_manage MCP tool: update / delete / correct / rate existing memories.

[INPUT]
- toolkits.memory.agent_surface.write_failure_feedback (POS: LLM-readable write failure messages)
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager; protected memories are never touched by external agents, TYPE_CHECKING only)

[OUTPUT]
- register_manage_tool: register memory_manage on an MCPServer

[POS]
Write plane (modify / remove) of the MCP adapter; creation lives in store_tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.mcpserver import MCPServer

from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.common import CATEGORY_TO_TYPE, ManagerResolver
from myrm_agent_harness.toolkits.memory.agent_surface.write_failure_feedback import write_failure_feedback
from myrm_agent_harness.toolkits.memory.types import MemoryType

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

_VALID_ACTIONS = ("update", "delete", "correct", "rate")
_VALID_MANAGE_CATEGORIES = ("knowledge", "event", "preference", "rule")
_VECTOR_TYPES = (MemoryType.SEMANTIC, MemoryType.EPISODIC)


async def _rate(
    mgr: MemoryManager,
    mem_type: MemoryType,
    category: str,
    memory_id: str,
    rating_score: int | None,
) -> str:
    if rating_score is None:
        return "Rate requires 'rating_score' (1-5)."
    if mem_type not in _VECTOR_TYPES:
        return "Rate is only supported for knowledge/event memories."
    if not mgr.has_vector:
        return f"{category} memory is not enabled."
    if await mgr.rate_memory(memory_id, rating_score):
        return f"Memory rated (ID: {memory_id}, score: {rating_score})"
    return f"Memory not found (ID: {memory_id})"


async def _delete(mgr: MemoryManager, mem_type: MemoryType, category: str, memory_id: str) -> str:
    if mem_type in _VECTOR_TYPES:
        if not mgr.has_vector:
            return f"{category} memory is not enabled."
        collection = (
            mgr.config.semantic_collection if mem_type == MemoryType.SEMANTIC else mgr.config.episodic_collection
        )
        deleted = await mgr.delete_memory(collection, [memory_id], allow_protected=False)
        return f"Memory deleted (ID: {memory_id})" if deleted > 0 else f"Memory not found (ID: {memory_id})"

    if mem_type == MemoryType.PROFILE:
        return "Profile attributes cannot be deleted via memory_manage."

    if not mgr.has_relational:
        return "Procedural memory is not enabled."
    if await mgr.delete_rule(memory_id, allow_protected=False):
        return f"Rule deleted (ID: {memory_id})"
    return (
        f"Cannot delete rule (ID: {memory_id}): "
        "it may be user-protected or not found. Rules the user explicitly "
        "locked cannot be deleted by the agent."
    )


async def _update(mgr: MemoryManager, memory_id: str, new_content: str | None, new_importance: float | None) -> str:
    if not new_content:
        return "Update requires 'new_content'."
    updated = await mgr.update_memory(
        memory_id,
        content=new_content,
        importance=new_importance,
        allow_protected=False,
    )
    return f"Memory updated (ID: {updated.id})"


async def _correct(mgr: MemoryManager, mem_type: MemoryType, memory_id: str, new_content: str | None) -> str:
    if not new_content:
        return "Correct requires 'new_content' with the corrected fact."
    if mem_type != MemoryType.SEMANTIC:
        return "Correct is only supported for knowledge memories."
    if not mgr.has_vector:
        return "Knowledge memory is not enabled."
    correction = await mgr.correct_memory(memory_id, new_content, allow_protected=False)
    return f"Memory corrected (new ID: {correction.id}). Prior entry {memory_id} kept in history."


def register_manage_tool(mcp: MCPServer, resolve: ManagerResolver, *, description: str) -> None:
    """Register memory_manage on ``mcp``; ``resolve`` supplies the request's MemoryManager."""

    @mcp.tool(name="memory_manage", description=description)
    async def memory_manage(
        action: str,
        memory_id: str,
        category: str,
        new_content: str | None = None,
        new_importance: float | None = None,
        rating_score: int | None = None,
    ) -> str:
        """Manage an existing memory.

        Args:
            action: "update", "delete", "correct", or "rate".
            memory_id: Memory ID from memory_recall results.
            category: knowledge | event | preference | rule (instruction saves use category=rule).
            new_content: Required for update/correct actions.
            new_importance: Optional new importance score (0.0-1.0).
            rating_score: Required for rate action (1-5, 1=bad, 5=excellent).
        """
        if action not in _VALID_ACTIONS:
            return f"Error: invalid action '{action}'. Valid: {', '.join(_VALID_ACTIONS)}"

        mem_type = CATEGORY_TO_TYPE.get(category)
        if mem_type is None or category not in _VALID_MANAGE_CATEGORIES:
            return f"Error: invalid category '{category}'. Valid for manage: {', '.join(_VALID_MANAGE_CATEGORIES)}"

        mgr = resolve()
        try:
            if action == "rate":
                return await _rate(mgr, mem_type, category, memory_id, rating_score)
            if action == "delete":
                return await _delete(mgr, mem_type, category, memory_id)
            if action == "update":
                return await _update(mgr, memory_id, new_content, new_importance)
            return await _correct(mgr, mem_type, memory_id, new_content)
        except Exception as e:
            return write_failure_feedback(
                "MCP memory_manage", e, fallback="Failed to manage memory", memory_id=memory_id
            )
