"""Data models and exception contracts for Prompt Cache stability guard and frozen snapshots.

[INPUT]
None (Pure dataclasses, Pydantic contracts, and custom exception definitions).

[OUTPUT]
CapacityLimitConfig: Character limit configuration for MEMORY and USER markdown blocks.
FrozenMemorySnapshot: Immutable snapshot containing serialized memory blocks and mutation metadata.
AtomicReplacePayload: Input parameters for single-transaction replace operations.
CapacityOverflowError: Explicit capacity limit exception requiring LLM semantic consolidation.
SecurityThreatBlockedError: Security exception raised when credential leaks or high-risk patterns are detected.

[POS]
前缀缓存稳定守卫与不可变常驻记忆快照模型层。定义 MEMORY/USER 紧凑字符上限（2200/1375 字符）、
不可变快照结构、原子替换载荷及容量超限显式语义决策异常合约。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CapacityLimitConfig:
    """Character budget limits for in-context resident memory blocks."""

    max_memory_chars: int = 2200
    max_user_chars: int = 1375


@dataclass(frozen=True, slots=True)
class AtomicReplacePayload:
    """Payload for atomic swap operation (delete old entry, insert new entry)."""

    target_category: str
    remove_target: str
    new_content: str


@dataclass(frozen=True, slots=True)
class FrozenMemorySnapshot:
    """Immutable resident memory snapshot bound to an active conversation session."""

    session_id: str
    memory_content: str
    user_profile_content: str
    snapshot_version: str
    created_at: datetime
    pending_updates_count: int = 0

    def formatted_system_prompt_block(self) -> str:
        """Render deterministic compact markdown block for System Prompt injection."""
        lines: list[str] = [
            "# Project and Resident Memory (Immutable Frozen Snapshot)",
            "<!-- Cache-Stability: prefix locked for entire active session -->",
            "## MEMORY.md",
            self.memory_content.strip() or "_No resident project memory recorded._",
            "",
            "## USER.md",
            self.user_profile_content.strip() or "_No user profile recorded._",
        ]
        return "\n".join(lines).strip()

    def total_characters(self) -> int:
        """Return combined total character count of resident memory blocks."""
        return len(self.memory_content) + len(self.user_profile_content)


class CapacityOverflowError(Exception):
    """Raised when resident memory exceeds character limits without silent truncation.

    Forces the agent to perform explicit semantic consolidation or retire stale items.
    """

    def __init__(
        self,
        category: str,
        current_chars: int,
        max_chars: int,
        existing_items: list[str],
    ) -> None:
        self.category = category
        self.current_chars = current_chars
        self.max_chars = max_chars
        self.existing_items = existing_items
        message = (
            f"Resident memory capacity overflow in '{category}': current {current_chars} chars "
            f"exceeds limit of {max_chars} chars. Silent truncation is disallowed. "
            f"You must actively consolidate, merge, or remove stale items from the following entries:\n"
            + "\n".join(f"- {item}" for item in existing_items)
        )
        super().__init__(message)


class SecurityThreatBlockedError(Exception):
    """Raised when memory write is blocked due to credential leak or injection threat."""

    def __init__(self, reason: str, detected_patterns: list[str]) -> None:
        self.reason = reason
        self.detected_patterns = detected_patterns
        patterns_repr = ", ".join(detected_patterns)
        super().__init__(f"Memory write blocked due to security violation ({reason}): [{patterns_repr}]")
