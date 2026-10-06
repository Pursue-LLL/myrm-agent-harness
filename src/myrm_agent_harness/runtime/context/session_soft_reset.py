"""Session state soft-reset and instant memory consolidation engine."""

from __future__ import annotations

import time
from threading import RLock

from myrm_agent_harness.runtime.context.session_soft_reset_types import (
    ResetTriggerKind,
    SoftResetExecutionResult,
    VaultedConsolidatedMemory,
    VaultedMemoryItem,
)


class ResetIntentDetector:
    """Detects whether a user input or trigger event signals a session soft-reset request."""

    _SLASH_COMMANDS: tuple[str, ...] = ("/reset", "/clear", "/restart")
    _NATURAL_PATTERNS: tuple[str, ...] = (
        "重新开始聊",
        "重新开始",
        "清空当前对话",
        "清空对话",
        "聊乱了",
        "翻篇吧",
        "清空上下文",
        "重置当前会话",
        "start over",
        "reset conversation",
        "clean context",
    )

    @classmethod
    def detect_reset_intent(cls, text: str) -> tuple[bool, ResetTriggerKind | None]:
        """Checks if the input text represents a reset intent."""
        clean = text.strip().lower()
        if clean in cls._SLASH_COMMANDS:
            return True, ResetTriggerKind.EXPLICIT_SLASH_COMMAND

        for pat in cls._NATURAL_PATTERNS:
            if pat in clean:
                return True, ResetTriggerKind.NATURAL_LANGUAGE_INTENT

        return False, None


class InstantMemoryVault:
    """Extracts and vaults key facts, user preferences, and lessons prior to clearing context."""

    @classmethod
    def consolidate_and_vault(
        cls,
        session_id: str,
        messages: list[dict[str, str]],
        current_time: float | None = None,
    ) -> VaultedConsolidatedMemory:
        """Consolidates messages into an immutable vaulted memory package."""
        now = time.time() if current_time is None else current_time
        items: list[VaultedMemoryItem] = []

        for turn_idx, msg in enumerate(messages):
            content = msg.get("content", "").strip()
            if not content:
                continue

            lines = content.splitlines()
            for line in lines:
                l_strip = line.strip()
                if not l_strip:
                    continue
                lower = l_strip.lower()

                if any(k in lower for k in ("偏好", "习惯", "prefer", "preference", "喜欢使用")):
                    items.append(
                        VaultedMemoryItem(
                            item_id=f"pref-{turn_idx}-{len(items)}",
                            category="preference",
                            content=l_strip,
                            extracted_from_turn=turn_idx,
                        )
                    )
                elif any(k in lower for k in ("教训", "踩坑", "排查发现", "lesson", "fixed bug", "gotcha")):
                    items.append(
                        VaultedMemoryItem(
                            item_id=f"lesson-{turn_idx}-{len(items)}",
                            category="lesson",
                            content=l_strip,
                            extracted_from_turn=turn_idx,
                        )
                    )
                elif any(k in lower for k in ("配置", "约定", "端口", "path:", "convention", "config")):
                    items.append(
                        VaultedMemoryItem(
                            item_id=f"fact-{turn_idx}-{len(items)}",
                            category="fact",
                            content=l_strip,
                            extracted_from_turn=turn_idx,
                        )
                    )

        digest = (
            f"Vaulted {len(items)} key learnings (preferences/facts/lessons) from "
            f"{len(messages)} turns in session '{session_id}'."
        )

        return VaultedConsolidatedMemory(
            session_id=session_id,
            vaulted_at=now,
            items=tuple(items[:20]),  # Bound the maximum vaulted memory items
            pre_reset_message_count=len(messages),
            summary_digest=digest,
        )


class SessionSoftResetEngine:
    """Coordinates soft-reset lifecycle: vaulting memories, wiping message window, and reloading baseline."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._vault_store: dict[str, list[VaultedConsolidatedMemory]] = {}

    def execute_soft_reset(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        trigger: ResetTriggerKind,
        baseline_system_prompt: str,
        current_time: float | None = None,
    ) -> SoftResetExecutionResult:
        """Executes soft reset, returning the vaulted memory and refreshed pristine context."""
        now = time.time() if current_time is None else current_time

        # Step 1: Pre-reset memory snapshot & vaulting
        vaulted = InstantMemoryVault.consolidate_and_vault(session_id, messages, current_time=now)

        with self._lock:
            self._vault_store.setdefault(session_id, []).append(vaulted)

        # Step 2: Build fresh reloaded prompt incorporating vaulted memories
        reloaded_prompt = baseline_system_prompt.strip()
        if vaulted.items:
            memories_xml = "\n".join(
                f"  <memory category=\"{it.category}\">{it.content}</memory>"
                for it in vaulted.items
            )
            learnings_block = (
                f"\n\n<vaulted_learnings from_session=\"{session_id}\">\n"
                f"{memories_xml}\n"
                f"</vaulted_learnings>"
            )
            reloaded_prompt += learnings_block

        tokens = max(1, len(reloaded_prompt) // 4)

        ack_msg = (
            f"会话已干净翻篇！短期对话窗口已重置（清空了 {len(messages)} 条历史），"
            f"后台已为您自动留存 {len(vaulted.items)} 条关键偏好与环境约定，长期认知完好无损。"
        )

        return SoftResetExecutionResult(
            session_id=session_id,
            trigger_kind=trigger,
            cleared_message_count=len(messages),
            vaulted_memory=vaulted,
            reloaded_baseline_tokens=tokens,
            system_baseline_prompt=reloaded_prompt,
            acknowledgment_message=ack_msg,
        )

    def get_session_vaulted_memories(self, session_id: str) -> list[VaultedConsolidatedMemory]:
        """Retrieves historical vaulted memories for auditing or inspection."""
        with self._lock:
            return list(self._vault_store.get(session_id, []))
