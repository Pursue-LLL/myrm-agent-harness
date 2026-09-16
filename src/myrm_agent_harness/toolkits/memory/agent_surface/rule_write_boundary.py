"""User-endorsed rule protection boundary for agent-facing memory operations.

Rules the user explicitly locked (``is_user_locked``) belong to the user: the
agent may read them, but must not delete or rewrite them. Deletion is already
enforced inside ``MemoryManager.delete_rule``; rewriting needs a boundary here
because ``MemoryManager.update_memory`` also serves the WebUI path, which the
user is entitled to use on their own locked rules.

[INPUT]
- myrm_agent_harness.toolkits.memory.types::AnyMemory (POS: 记忆类型定义，含 is_user_locked)

[OUTPUT]
- get_user_locked_rule / rule_rewrite_protection_message: Guard for agent-surface rewrites.

[POS]
Agent 面向的用户背书规则保护边界。保证「被用户显式保护的规则，Agent 不能改写」，同时不阻断 WebUI 编辑路径。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.types import AnyMemory

logger = logging.getLogger(__name__)


def get_user_locked_rule(memory: AnyMemory | None) -> AnyMemory | None:
    """Return the memory when it is a user-locked procedural rule, else None."""
    from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

    if isinstance(memory, ProceduralMemory) and memory.is_user_locked:
        return memory
    return None


def rule_rewrite_protection_message(memory_id: str) -> str:
    """Rejection message returned to the agent for a locked rule rewrite."""
    return (
        f"Cannot update rule (ID: {memory_id}): the user explicitly locked this rule, "
        "so the agent must not rewrite its content. Ask the user to unlock it first "
        "if the rule needs to change."
    )
