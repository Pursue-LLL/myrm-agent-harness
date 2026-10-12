"""memory_manage_tool: update / delete / correct / rate / discard existing memories.

[INPUT]
- toolkits.memory.agent_surface.memory_agent_tools.common::CATEGORY_TO_TYPE (POS: Stateless helpers for memory_search/save/manage tool arguments)
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager; protected memories are never touched by the agent)
- toolkits.memory.types::MemoryType (POS: memory type enum)
- toolkits.memory.agent_surface.write_failure_feedback (POS: LLM-readable write failure messages)

[OUTPUT]
- MemoryManageInput: pydantic args schema of memory_manage_tool
- build_memory_manage_tool: bind memory_manage_tool to a manager

[POS]
Write plane (modify / remove) of the agent memory tools; creation lives in save_tool.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools.common import CATEGORY_TO_TYPE
from myrm_agent_harness.toolkits.memory.agent_surface.write_failure_feedback import write_failure_feedback
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import MemoryType

ManageAction = Literal["update", "delete", "correct", "rate", "discard"]
ManageCategory = Literal["knowledge", "event", "preference", "rule"]

_VECTOR_TYPES = (MemoryType.SEMANTIC, MemoryType.EPISODIC)


class MemoryManageInput(BaseModel):
    action: ManageAction = Field(
        description=(
            "update: wording/importance; correct: wrong knowledge; delete; rate; discard: prune outdated memory"
        ),
    )
    memory_id: str = Field(description="Memory ID from memory_search_tool results.")
    category: ManageCategory = Field(
        description=("knowledge | event | preference | rule — instruction saves use category=rule (always trigger)"),
    )
    new_content: str | None = Field(
        default=None,
        description=("Required for update (wording/importance) and correct (wrong fact, knowledge only)."),
    )
    new_importance: float | None = Field(
        default=None,
        description="Optional new importance for update.",
    )
    rating_score: int | None = Field(
        default=None,
        description="Required for rate; integer 1-5.",
    )


def _vector_collection(manager: MemoryManager, mem_type: MemoryType) -> str:
    config = manager.config
    return config.semantic_collection if mem_type == MemoryType.SEMANTIC else config.episodic_collection


async def _rate(
    manager: MemoryManager,
    mem_type: MemoryType,
    category: str,
    memory_id: str,
    rating_score: int | None,
) -> str:
    if rating_score is None:
        return "Rate requires 'rating_score' (1-5)."
    if mem_type not in _VECTOR_TYPES:
        return "Rate action is only supported for knowledge/event memories."
    if not manager.has_vector:
        return f"{category} memory is not enabled."
    if await manager.rate_memory(memory_id, rating_score):
        return f"Memory rated (ID: {memory_id}, score: {rating_score})"
    return f"Memory not found (ID: {memory_id})"


async def _delete(manager: MemoryManager, mem_type: MemoryType, category: str, memory_id: str) -> str:
    if mem_type in _VECTOR_TYPES:
        if not manager.has_vector:
            return f"{category} memory is not enabled."
        deleted = await manager.delete_memory(_vector_collection(manager, mem_type), [memory_id], allow_protected=False)
        if deleted > 0:
            return f"Memory deleted (ID: {memory_id})"
        return (
            f"Cannot delete memory (ID: {memory_id}): "
            "it may be protected by the user or not found. Protected memories cannot be deleted by the agent."
        )

    if mem_type == MemoryType.PROFILE:
        return "Profile attributes cannot be deleted via memory_manage."

    if mem_type == MemoryType.PROCEDURAL:
        if not manager.has_relational:
            return "Procedural memory is not enabled."
        if await manager.delete_rule(memory_id, allow_protected=False):
            return f"Rule deleted (ID: {memory_id})"
        return (
            f"Cannot delete rule (ID: {memory_id}): "
            "it may be user-protected or not found. Rules the user explicitly "
            "locked cannot be deleted by the agent."
        )

    return "Unknown action: delete"


async def _update(manager: MemoryManager, memory_id: str, new_content: str | None, new_importance: float | None) -> str:
    if not new_content:
        return "Update requires 'new_content'."
    updated = await manager.update_memory(
        memory_id,
        content=new_content,
        importance=new_importance,
        allow_protected=False,
    )
    return f"Memory updated (ID: {updated.id})"


async def _correct(manager: MemoryManager, mem_type: MemoryType, memory_id: str, new_content: str | None) -> str:
    if not new_content:
        return "Correct requires 'new_content' with the corrected fact."
    if mem_type != MemoryType.SEMANTIC:
        return "Correct action is only supported for knowledge memories."
    if not manager.has_vector:
        return "Knowledge memory is not enabled."
    correction = await manager.correct_memory(memory_id, new_content, allow_protected=False)
    return f"Memory corrected (new ID: {correction.id}). Prior entry {memory_id} kept in history."


async def _discard(manager: MemoryManager, mem_type: MemoryType, category: str, memory_id: str) -> str:
    if mem_type in _VECTOR_TYPES:
        if not manager.has_vector:
            return f"{category} memory is not enabled."
        discarded = await manager.delete_memory(
            _vector_collection(manager, mem_type), [memory_id], allow_protected=False
        )
        if discarded > 0:
            return f"Memory discarded (ID: {memory_id})"
        return f"Cannot discard memory (ID: {memory_id}): protected or not found."

    if mem_type == MemoryType.PROCEDURAL:
        if not manager.has_relational:
            return "Procedural memory is not enabled."
        if await manager.delete_rule(memory_id, allow_protected=False):
            return f"Rule discarded (ID: {memory_id})"
        return f"Cannot discard rule (ID: {memory_id}): protected or not found."

    return f"Discard action is not supported for category: {category}"


def build_memory_manage_tool(manager: MemoryManager, *, description: str) -> BaseTool:
    """Create memory_manage_tool bound to ``manager``."""

    @tool("memory_manage_tool", description=description, args_schema=MemoryManageInput)
    async def memory_manage(
        action: ManageAction,
        memory_id: str,
        category: ManageCategory,
        new_content: str | None = None,
        new_importance: float | None = None,
        rating_score: int | None = None,
    ) -> str:
        """Update, delete, correct, or rate an existing memory entry."""
        try:
            mem_type = CATEGORY_TO_TYPE.get(category)
            if mem_type is None:
                return f"Unknown category: {category}"

            if action == "rate":
                return await _rate(manager, mem_type, category, memory_id, rating_score)
            if action == "delete":
                return await _delete(manager, mem_type, category, memory_id)
            if action == "update":
                return await _update(manager, memory_id, new_content, new_importance)
            if action == "correct":
                return await _correct(manager, mem_type, memory_id, new_content)
            if action == "discard":
                return await _discard(manager, mem_type, category, memory_id)
            return f"Unknown action: {action}"
        except Exception as e:
            return write_failure_feedback("memory_manage", e, fallback="Failed to manage memory", memory_id=memory_id)

    return memory_manage
