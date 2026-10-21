"""Agent-facing rejection message for user-protected memories.

``MemoryManager`` refuses automated and agent writes to a protected memory
(``pinned`` for vector entries, ``is_user_locked`` for procedural rules) by
raising ``MemoryProtectedError``. This module owns the single message the agent
surfaces back to the model for that refusal, so every agent entry point explains
the rejection the same way.

[INPUT]
- (none) — dependency-free so any agent surface can format the rejection.

[OUTPUT]
- rule_write_protection_message: Rejection text for agent-facing protected writes.

[POS]
Agent 面向的用户保护记忆改写拒绝文案 SSOT。保护判定本身在 ``MemoryManager`` 内统一执行，本模块只负责解释拒绝原因。
"""

from __future__ import annotations


def rule_write_protection_message(memory_id: str) -> str:
    """Rejection message returned to the agent for a protected memory write."""
    return (
        f"Cannot update memory (ID: {memory_id}): the user explicitly protected this memory, "
        "so the agent must not rewrite its content or status. Ask the user to release the "
        "protection first if it needs to change."
    )


__all__ = ["rule_write_protection_message"]
