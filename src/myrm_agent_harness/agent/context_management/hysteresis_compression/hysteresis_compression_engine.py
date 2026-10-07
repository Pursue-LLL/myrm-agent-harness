"""Core engine for Dual-Watermark Hysteresis Compression and Cooldown Ladder Suite.

Controls context compaction frequency via high/low hysteresis watermarks, enforces
adaptive cooldown intervals to prevent rapid re-compression thrashing, and shields
critical memory sanctuary blocks (genesis prompts, active todos, diff anchors).
"""

from __future__ import annotations

import re
from typing import Sequence
from myrm_agent_harness.agent.context_management.hysteresis_compression.hysteresis_compression_types import (
    CooldownStatus,
    HysteresisConfig,
    HysteresisEvaluation,
    HysteresisExecutionReport,
    SanctuaryBlock,
    SanctuaryCategory,
    WatermarkTier,
)


class HysteresisCompressionEngine:
    """Engine orchestrating hysteresis gap compaction and anti-amnesia memory sanctuary."""

    def __init__(self, config: HysteresisConfig | None = None) -> None:
        self.config: HysteresisConfig = config or HysteresisConfig()
        self._cooldown_until_turn: int = 0
        self._ladder_stage: int = 0
        self._sanctuary_registry: dict[str, SanctuaryBlock] = {}

    def get_cooldown_status(self, current_turn: int) -> CooldownStatus:
        """Inspect current cooldown ladder state relative to current turn index."""
        remaining = max(0, self._cooldown_until_turn - current_turn)
        in_cooldown = remaining > 0
        current_duration = min(
            self.config.base_cooldown_turns + (self._ladder_stage * self.config.ladder_escalation_step),
            self.config.max_cooldown_turns,
        )
        return CooldownStatus(
            is_in_cooldown=in_cooldown,
            remaining_turns=remaining,
            current_ladder_step=self._ladder_stage,
            ladder_cooldown_turns=current_duration,
        )

    def evaluate(
        self,
        current_tokens: int,
        current_turn: int,
        max_tokens: int | None = None,
    ) -> HysteresisEvaluation:
        """Evaluate context consumption against hysteresis watermarks and cooldown ladder."""
        effective_limit = max_tokens if max_tokens is not None and max_tokens > 0 else self.config.max_context_tokens
        usage_ratio = current_tokens / effective_limit

        cooldown_status = self.get_cooldown_status(current_turn)
        is_emergency = usage_ratio >= self.config.emergency_watermark_ratio

        if is_emergency:
            tier = WatermarkTier.EMERGENCY_OVERFLOW
        elif usage_ratio >= self.config.high_watermark_ratio:
            tier = WatermarkTier.HIGH_WATERMARK
        elif usage_ratio >= self.config.low_watermark_ratio:
            tier = WatermarkTier.IN_GAP
        else:
            tier = WatermarkTier.NORMAL

        target_low_tokens = int(effective_limit * self.config.low_watermark_ratio)
        target_reclaim = max(0, current_tokens - target_low_tokens)

        if is_emergency:
            return HysteresisEvaluation(
                should_compress=True,
                tier=tier,
                current_tokens=current_tokens,
                max_context_tokens=effective_limit,
                usage_ratio=round(usage_ratio, 4),
                target_reclaim_tokens=target_reclaim,
                is_emergency=True,
                cooldown_suppressed=False,
                decision_reason=(
                    f"Emergency watermark breach ({usage_ratio:.1%} >= {self.config.emergency_watermark_ratio:.1%}). "
                    "Overriding cooldown ladder to prevent physical out-of-memory collapse."
                ),
            )

        if cooldown_status.is_in_cooldown:
            return HysteresisEvaluation(
                should_compress=False,
                tier=tier,
                current_tokens=current_tokens,
                max_context_tokens=effective_limit,
                usage_ratio=round(usage_ratio, 4),
                target_reclaim_tokens=target_reclaim,
                is_emergency=False,
                cooldown_suppressed=True,
                decision_reason=(
                    f"Active cooldown ladder ({cooldown_status.remaining_turns} turns remaining). "
                    "Suppressing compaction to preserve cognitive stability and prompt cache."
                ),
            )

        if tier == WatermarkTier.HIGH_WATERMARK:
            return HysteresisEvaluation(
                should_compress=True,
                tier=tier,
                current_tokens=current_tokens,
                max_context_tokens=effective_limit,
                usage_ratio=round(usage_ratio, 4),
                target_reclaim_tokens=target_reclaim,
                is_emergency=False,
                cooldown_suppressed=False,
                decision_reason=(
                    f"High watermark reached ({usage_ratio:.1%} >= {self.config.high_watermark_ratio:.1%}). "
                    f"Targeting deep single-pass compaction down to {self.config.low_watermark_ratio:.1%} "
                    f"(reclaim ~{target_reclaim} tokens, opening ~{self.config.high_watermark_ratio - self.config.low_watermark_ratio:.1%} buffer)."
                ),
            )

        return HysteresisEvaluation(
            should_compress=False,
            tier=tier,
            current_tokens=current_tokens,
            max_context_tokens=effective_limit,
            usage_ratio=round(usage_ratio, 4),
            target_reclaim_tokens=0,
            is_emergency=False,
            cooldown_suppressed=False,
            decision_reason=(
                f"Context usage ({usage_ratio:.1%}) within safe operating envelope "
                f"(Low: {self.config.low_watermark_ratio:.1%}, High: {self.config.high_watermark_ratio:.1%})."
            ),
        )

    def register_sanctuary(self, block: SanctuaryBlock) -> None:
        """Register an immutable sanctuary block exempt from compaction."""
        self._sanctuary_registry[block.block_id] = block

    def unregister_sanctuary(self, block_id: str) -> bool:
        """Unregister a sanctuary block when its task completes or invariant lifts."""
        return self._sanctuary_registry.pop(block_id, None) is not None

    def list_sanctuary_blocks(self) -> list[SanctuaryBlock]:
        """Return all active sanctuary blocks."""
        return list(self._sanctuary_registry.values())

    def get_total_sanctuary_tokens(self) -> int:
        """Calculate total estimated tokens reserved across all sanctuary blocks."""
        return sum(block.estimated_tokens for block in self._sanctuary_registry.values())

    def record_compression_success(self, current_turn: int) -> int:
        """Record completed compaction, step up ladder, and arm cooldown period."""
        cooldown_turns = min(
            self.config.base_cooldown_turns + (self._ladder_stage * self.config.ladder_escalation_step),
            self.config.max_cooldown_turns,
        )
        self._cooldown_until_turn = current_turn + cooldown_turns
        self._ladder_stage += 1
        return cooldown_turns

    def reset_cooldown(self) -> None:
        """Reset cooldown ladder and turn counter (e.g. on new session or explicit user clear)."""
        self._cooldown_until_turn = 0
        self._ladder_stage = 0

    def extract_sanctuary_blocks_from_messages(
        self,
        messages: Sequence[dict[str, str]],
    ) -> list[SanctuaryBlock]:
        """Auto-detect and extract genesis directives, pending todos, and code diffs."""
        discovered: list[SanctuaryBlock] = []

        for idx, msg in enumerate(messages):
            content = msg.get("content", "")
            role = msg.get("role", "")

            # 1. Genesis Directive (First system or user instruction)
            if idx == 0 and role in ("system", "user") and content.strip():
                est_tokens = max(1, int(len(content) / self.config.bytes_per_token_estimate))
                block = SanctuaryBlock(
                    block_id=f"sanctuary_genesis_{idx}",
                    category=SanctuaryCategory.GENESIS_PROMPT,
                    content=content,
                    estimated_tokens=est_tokens,
                    metadata={"role": role, "index": str(idx)},
                )
                discovered.append(block)
                self.register_sanctuary(block)

            # 2. Active Checklist or Unfinished Todo Items
            if re.search(r"-\s*\[\s*\]\s+.+", content) or "TODO:" in content:
                todo_matches = re.findall(r"-\s*\[\s*\]\s+[^\n]+", content)
                if todo_matches:
                    todo_snippet = "\n".join(todo_matches)
                    est_tokens = max(1, int(len(todo_snippet) / self.config.bytes_per_token_estimate))
                    block = SanctuaryBlock(
                        block_id=f"sanctuary_todo_{idx}",
                        category=SanctuaryCategory.ACTIVE_TODO,
                        content=todo_snippet,
                        estimated_tokens=est_tokens,
                        metadata={"source_message_index": str(idx)},
                    )
                    discovered.append(block)
                    self.register_sanctuary(block)

            # 3. Code Diff Anchors
            if "diff --git" in content or re.search(r"@@ -\d+,\d+ \+\d+,\d+ @@", content):
                est_tokens = max(1, int(len(content) / self.config.bytes_per_token_estimate))
                block = SanctuaryBlock(
                    block_id=f"sanctuary_diff_{idx}",
                    category=SanctuaryCategory.DIFF_ANCHOR,
                    content=content,
                    estimated_tokens=est_tokens,
                    metadata={"source_message_index": str(idx)},
                )
                discovered.append(block)
                self.register_sanctuary(block)

            # 4. Explicit Sanctuary Tags
            if "<sanctuary>" in content and "</sanctuary>" in content:
                match = re.search(r"<sanctuary>(.*?)</sanctuary>", content, re.DOTALL)
                if match:
                    inner_content = match.group(1).strip()
                    est_tokens = max(1, int(len(inner_content) / self.config.bytes_per_token_estimate))
                    block = SanctuaryBlock(
                        block_id=f"sanctuary_tag_{idx}",
                        category=SanctuaryCategory.USER_EXPLICIT,
                        content=inner_content,
                        estimated_tokens=est_tokens,
                        metadata={"source_message_index": str(idx)},
                    )
                    discovered.append(block)
                    self.register_sanctuary(block)

        return discovered

    def apply_hysteresis_compaction(
        self,
        messages: Sequence[dict[str, str]],
        current_turn: int,
        target_reclaim_tokens: int,
    ) -> tuple[list[dict[str, str]], HysteresisExecutionReport]:
        """Perform deep compaction targeting low watermark while strictly preserving sanctuaries."""
        # 1. Discover and protect sanctuaries
        self.extract_sanctuary_blocks_from_messages(messages)
        sanctuary_blocks = self.list_sanctuary_blocks()
        sanctuary_tokens = self.get_total_sanctuary_tokens()

        sanctuary_contents = {b.content for b in sanctuary_blocks}

        original_chars = sum(len(m.get("content", "")) for m in messages)
        original_tokens = max(1, int(original_chars / self.config.bytes_per_token_estimate))

        compacted_messages: list[dict[str, str]] = []
        tokens_reclaimed = 0

        # Preserve the most recent 2 turns unconditionally
        recent_cutoff = max(0, len(messages) - 2)

        for idx, msg in enumerate(messages):
            content = msg.get("content", "")
            role = msg.get("role", "")

            # If inside sanctuary or recent turn, preserve 100% untouched
            is_sanctuary = any(
                content == s_content or s_content in content
                for s_content in sanctuary_contents
            )
            if idx >= recent_cutoff or is_sanctuary:
                compacted_messages.append(dict(msg))
                continue

            # If target reclaim not yet met and content is verbose, stub it
            if tokens_reclaimed < target_reclaim_tokens and len(content) > 300:
                stub_text = f"[Compacted Context Turn #{idx} ({role}) · Retaining sanctuary anchors & core facts]"
                old_tokens = int(len(content) / self.config.bytes_per_token_estimate)
                new_tokens = int(len(stub_text) / self.config.bytes_per_token_estimate)
                reclaimed = max(0, old_tokens - new_tokens)

                compacted_messages.append({
                    "role": role,
                    "content": stub_text,
                })
                tokens_reclaimed += reclaimed
            else:
                compacted_messages.append(dict(msg))

        activated_cooldown = self.record_compression_success(current_turn)
        final_chars = sum(len(m.get("content", "")) for m in compacted_messages)
        final_tokens = max(1, int(final_chars / self.config.bytes_per_token_estimate))

        report = HysteresisExecutionReport(
            original_tokens=original_tokens,
            reclaimed_tokens=tokens_reclaimed,
            final_tokens=final_tokens,
            sanctuary_tokens_preserved=sanctuary_tokens,
            sanctuary_blocks_count=len(sanctuary_blocks),
            cooldown_activated_turns=activated_cooldown,
            ladder_stage=self._ladder_stage,
        )

        return compacted_messages, report
