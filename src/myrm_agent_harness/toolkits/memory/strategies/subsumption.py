"""Memory Subsumption Engine (Cognitive Consolidation).


[INPUT]
- memory.manager::MemoryManager (POS: unified memory manager facade)
- memory.types::MemoryType (POS: memory type enum)

[OUTPUT]
- run_subsumption: Cognitive erasure strategy (semantic containment judgment and soft-delete)

[POS]
Cognitive consolidation engine. Identifies and safely soft-deletes old semantic memories
that are completely subsumed by newly acquired higher-dimensional knowledge (e.g. Skills).
Protects memories containing unique user preferences from deletion.
"""

import logging

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import MemoryType

logger = logging.getLogger(__name__)

# We use BaseChatModel directly instead of ConsolidationLLMFunc

_JUDGE_PROMPT = """You are an expert AI cognitive consolidator. Your task is to evaluate if an old text memory can be safely DELETED because its contents are perfectly subsumed (covered) by a new piece of knowledge (e.g. a new code Skill or Wiki document).

If the new knowledge covers the core constraints, facts, and intent of the old memory, the old memory is redundant and should be deleted to prevent context bloat and cognitive conflicts.

However, if the old memory contains unique user preferences (e.g., "I like dark mode", "My name is John") that are NOT covered by the new knowledge, DO NOT delete it.

[Old Memory]
ID: {memory_id}
Content: {memory_content}

[New Knowledge]
{new_knowledge}

Evaluate whether the [Old Memory] is completely subsumed by the [New Knowledge].
Return ONLY a valid JSON object with exactly two keys:
- "subsumed": true if the old memory should be safely deleted, false otherwise.
- "reason": A brief 1-sentence explanation of why.
"""


async def judge_subsumption(
    memory_id: str, memory_content: str, new_knowledge: str, llm: BaseChatModel
) -> tuple[bool, str]:
    """Use an LLM to judge if an old memory is subsumed by new knowledge."""
    prompt = _JUDGE_PROMPT.format(memory_id=memory_id, memory_content=memory_content, new_knowledge=new_knowledge)

    try:
        from langchain_core.messages import HumanMessage
        from pydantic import BaseModel, Field

        class SubsumptionResult(BaseModel):
            subsumed: bool = Field(..., description="True if the old memory is completely subsumed by the new knowledge.")
            reason: str = Field(..., description="Detailed reasoning for the decision.")

        structured_llm = llm.with_structured_output(SubsumptionResult)
        result: SubsumptionResult = await structured_llm.ainvoke([HumanMessage(content=prompt)])

        return result.subsumed, result.reason
    except Exception as e:
        logger.warning("Failed to judge subsumption for memory %s: %s", memory_id, e)
        return False, f"Error: {e}"


async def find_subsumed_memories(
    manager: MemoryManager, new_knowledge: str, llm: BaseChatModel, max_candidates: int = 5
) -> list[str]:
    """Find and verify old memories that are subsumed by the new knowledge.

    Args:
        manager: The MemoryManager instance for the current user/sandbox.
        new_knowledge: The new skill code, wiki document, etc.
        llm_func: The LLM function to use as the judge.
        max_candidates: Max number of similar memories to retrieve and judge.

    Returns:
        List of memory IDs that should be deleted.
    """
    logger.info("Starting memory subsumption check for new knowledge snippet (%d chars)", len(new_knowledge))

    # 1. Search for top-K semantically similar old memories
    search_results = await manager.search(
        query=new_knowledge, memory_types=[MemoryType.SEMANTIC, MemoryType.PROCEDURAL], limit=max_candidates
    )

    if not search_results:
        logger.debug("No candidate memories found for subsumption.")
        return []

    subsumed_ids: list[str] = []

    # 2. Let the LLM judge each candidate
    for res in search_results:
        memory = await manager.get_memory(res.id)
        if not memory:
            continue

        # Skip memories that are already subsumed
        if memory.metadata.get("status") == "subsumed":
            continue

        is_subsumed, reason = await judge_subsumption(
            memory_id=memory.id, memory_content=memory.content, new_knowledge=new_knowledge, llm=llm
        )

        if is_subsumed:
            logger.info(" Memory %s subsumed by new knowledge. Reason: %s", memory.id, reason)
            subsumed_ids.append(memory.id)
        else:
            logger.debug("Memory %s NOT subsumed. Reason: %s", memory.id, reason)

    return subsumed_ids


async def apply_subsumption(manager: MemoryManager, memory_ids: list[str]) -> int:
    """Apply soft-delete to subsumed memories.

    Returns the number of successfully subsumed memories.
    """
    count = 0
    for mem_id in memory_ids:
        try:
            mem = await manager.get_memory(mem_id)
            if not mem:
                continue

            # Soft delete by marking status in metadata
            mem.metadata["status"] = "subsumed"

            from myrm_agent_harness.toolkits.memory.types import (
                MemoryStatus,
                ProceduralMemory,
                SemanticMemory,
            )

            if isinstance(mem, (SemanticMemory, ProceduralMemory)):
                await manager.update_memory(mem.id, metadata=mem.metadata, status=MemoryStatus.DISABLED)
            else:
                await manager.delete_memory(mem.scope.primary_namespace, [mem.id])
            count += 1
        except Exception as e:
            logger.error("Failed to apply subsumption to memory %s: %s", mem_id, e)

    return count


async def undo_subsumption(manager: MemoryManager, memory_ids: list[str]) -> int:
    """Undo a soft-delete (subsumption) by removing the status from metadata.

    Returns the number of successfully restored memories.
    """
    count = 0
    for mem_id in memory_ids:
        try:
            mem = await manager.get_memory(mem_id)
            if not mem:
                continue

            if mem.metadata.get("status") == "subsumed":
                # Remove soft delete marker
                del mem.metadata["status"]

                from myrm_agent_harness.toolkits.memory.types import (
                    MemoryStatus,
                    ProceduralMemory,
                    SemanticMemory,
                )

                if isinstance(mem, (SemanticMemory, ProceduralMemory)):
                    await manager.update_memory(mem.id, metadata=mem.metadata, status=MemoryStatus.ACTIVE)
                    count += 1
        except Exception as e:
            logger.error("Failed to undo subsumption for memory %s: %s", mem_id, e)

    return count
