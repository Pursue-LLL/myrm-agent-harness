"""Read-free memory tool suite with prompt cache stability and explicit capacity overflow gates.

[INPUT]
myrm_agent_harness.toolkits.memory.prompt_cache_guard.models::CapacityLimitConfig (POS: 字符上限配置模型)
myrm_agent_harness.toolkits.memory.prompt_cache_guard.models::CapacityOverflowError (POS: 容量超限异常)
myrm_agent_harness.toolkits.memory.prompt_cache_guard.security_gate::ZeroWidthAndCredentialLeakScanner (POS: 零宽字符与凭证安全门禁)
myrm_agent_harness.toolkits.memory.prompt_cache_guard.snapshot_provider::FrozenMemorySnapshotProvider (POS: 不可变快照提供者)

[OUTPUT]
ReadFreeMemoryToolSuite: Toolset providing add, atomic_replace, and remove operations without separate read, enforcing cache stability.

[POS]
前缀缓存稳定守卫之无读协议工具集。贯彻 Read-Free 协议（System Prompt 已包含冻结快照，移除冗余 read 工具），
提供单事务原子替换（先删后增防止超限死锁）、容量超限显式语义决策门禁、以及会话内写入延迟生效标记。
"""

from __future__ import annotations

import logging
from threading import Lock

from myrm_agent_harness.toolkits.memory.prompt_cache_guard.models import (
    CapacityLimitConfig,
    CapacityOverflowError,
)
from myrm_agent_harness.toolkits.memory.prompt_cache_guard.security_gate import (
    ZeroWidthAndCredentialLeakScanner,
)
from myrm_agent_harness.toolkits.memory.prompt_cache_guard.snapshot_provider import (
    FrozenMemorySnapshotProvider,
)

logger = logging.getLogger(__name__)


def _normalize_category(category: str) -> str:
    cleaned = category.strip().lower()
    if cleaned in ("memory", "project", "env", "convention"):
        return "memory"
    if cleaned in ("user", "profile", "preference"):
        return "user"
    return "memory"


class ReadFreeMemoryToolSuite:
    """Read-Free memory tool suite executing mutations with prompt cache lock."""

    def __init__(
        self,
        session_id: str,
        snapshot_provider: FrozenMemorySnapshotProvider,
        *,
        initial_memory_items: list[str] | None = None,
        initial_user_items: list[str] | None = None,
        capacity_config: CapacityLimitConfig | None = None,
    ) -> None:
        self.session_id = session_id
        self._provider = snapshot_provider
        self._config = capacity_config or CapacityLimitConfig()
        self._lock = Lock()
        self._memory_items: list[str] = list(initial_memory_items or [])
        self._user_items: list[str] = list(initial_user_items or [])

        # Ensure initial snapshot is locked in provider upon toolsuite construction
        self._provider.get_or_create_snapshot(
            session_id=session_id,
            memory_items=self._memory_items,
            user_items=self._user_items,
        )

    def _get_target_list_and_limit(self, norm_cat: str) -> tuple[list[str], int]:
        if norm_cat == "user":
            return (self._user_items, self._config.max_user_chars)
        return (self._memory_items, self._config.max_memory_chars)

    def _calculate_total_chars(self, items: list[str]) -> int:
        return sum(len(item.strip()) for item in items if item.strip())

    def memory_add(self, category: str, content: str) -> str:
        """Add new item to resident memory. Enforces security, duplicate checks, and capacity limits."""
        norm_cat = _normalize_category(category)
        with self._lock:
            target_list, max_limit = self._get_target_list_and_limit(norm_cat)

            # 1. Security & duplicate validation
            cleaned = ZeroWidthAndCredentialLeakScanner.validate_and_sanitize(
                content,
                target_list,
            )

            # 2. Capacity limit check
            projected_chars = self._calculate_total_chars(target_list) + len(cleaned)
            if projected_chars > max_limit:
                raise CapacityOverflowError(
                    category=norm_cat,
                    current_chars=projected_chars,
                    max_chars=max_limit,
                    existing_items=list(target_list),
                )

            # 3. Store in active state & record in-session mutation
            target_list.append(cleaned)
            self._provider.record_in_session_mutation(
                self.session_id,
                norm_cat,
                cleaned,
            )

            return (
                f"Memory entry recorded in '{norm_cat}'. It has been securely persisted and queued "
                f"for next-session system prompt injection. Active prompt remains frozen (0 cache miss)."
            )

    def memory_atomic_replace(
        self,
        category: str,
        remove_target: str,
        new_content: str,
    ) -> str:
        """Atomic swap in single transaction: removes old entry before checking capacity for new entry."""
        norm_cat = _normalize_category(category)
        with self._lock:
            target_list, max_limit = self._get_target_list_and_limit(norm_cat)

            # Locate target item to remove (case-insensitive substring or exact match)
            remove_idx = -1
            clean_remove = remove_target.strip().lower()
            for idx, item in enumerate(target_list):
                if item.strip().lower() == clean_remove or clean_remove in item.strip().lower():
                    remove_idx = idx
                    break

            if remove_idx == -1:
                return (
                    f"Replace failed: could not locate existing entry matching '{remove_target}'. "
                    f"Existing entries:\n" + "\n".join(f"- {it}" for it in target_list)
                )

            # Form candidate list without old item to prevent capacity deadlock
            temp_list = [it for idx, it in enumerate(target_list) if idx != remove_idx]

            # Security validate new content
            cleaned_new = ZeroWidthAndCredentialLeakScanner.validate_and_sanitize(
                new_content,
                temp_list,
            )

            # Check capacity with old item already removed
            projected_chars = self._calculate_total_chars(temp_list) + len(cleaned_new)
            if projected_chars > max_limit:
                raise CapacityOverflowError(
                    category=norm_cat,
                    current_chars=projected_chars,
                    max_chars=max_limit,
                    existing_items=list(temp_list),
                )

            # Atomic commit
            old_item = target_list.pop(remove_idx)
            target_list.append(cleaned_new)

            self._provider.record_in_session_mutation(
                self.session_id,
                norm_cat,
                f"REPLACED [{old_item}] -> [{cleaned_new}]",
            )

            return (
                f"Atomic replace succeeded in '{norm_cat}'. Removed stale entry and added new entry. "
                f"Queued for next session; current prompt prefix remains locked."
            )

    def memory_remove(self, category: str, target: str) -> str:
        """Remove matching item from resident memory."""
        norm_cat = _normalize_category(category)
        with self._lock:
            target_list, _ = self._get_target_list_and_limit(norm_cat)

            remove_idx = -1
            clean_target = target.strip().lower()
            for idx, item in enumerate(target_list):
                if item.strip().lower() == clean_target or clean_target in item.strip().lower():
                    remove_idx = idx
                    break

            if remove_idx == -1:
                return f"Remove failed: no matching entry found for '{target}'."

            removed = target_list.pop(remove_idx)
            self._provider.record_in_session_mutation(
                self.session_id,
                norm_cat,
                f"REMOVED [{removed}]",
            )
            return f"Removed entry: '{removed}'."

    def list_current_items(self, category: str) -> list[str]:
        """Return read-only snapshot of current resident items."""
        norm_cat = _normalize_category(category)
        with self._lock:
            target_list, _ = self._get_target_list_and_limit(norm_cat)
            return list(target_list)
