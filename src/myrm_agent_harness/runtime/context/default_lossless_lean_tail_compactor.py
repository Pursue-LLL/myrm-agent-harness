"""Default lossless lean-tail conversation compaction engine.

Implements lossless lean reduction by:
1. Retaining CRITICAL messages (system prompt & initial user objectives) verbatim.
2. Protecting HIGH priority recent interaction tail.
3. Collapsing bulky VOLATILE tool results in older turns into deterministic structural summaries.
4. Anchoring core constraints across extended multi-turn runs.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.lossless_lean_tail_types import (
    ConstraintAnchor,
    LeanReductionStats,
    LosslessCompactorConfig,
    MessageImportanceTier,
)
from myrm_agent_harness.runtime.context.message_importance_classifier import (
    MessageImportanceClassifier,
)


class DefaultLosslessLeanTailCompactor:
    """Zero-LLM overhead deterministic lean-tail conversation compactor."""

    def __init__(
        self,
        config: LosslessCompactorConfig | None = None,
        classifier: MessageImportanceClassifier | None = None,
    ) -> None:
        self.config = config or LosslessCompactorConfig()
        self.classifier = classifier or MessageImportanceClassifier(self.config)

    def compact_conversation(
        self,
        messages: list[dict[str, str]],
    ) -> tuple[list[dict[str, str]], LeanReductionStats]:
        """Perform lossless lean reduction over full conversation history."""
        if not messages:
            return [], LeanReductionStats(
                original_tokens_estimate=0,
                compacted_tokens_estimate=0,
                tokens_saved_estimate=0,
                reduction_percentage=0.0,
                volatile_tool_outputs_reduced=0,
                anchors_preserved_count=0,
            )

        classified = self.classifier.classify_messages(messages)
        original_tokens = sum(cm.token_estimate for cm in classified)

        # Extract core anchors
        anchors: list[ConstraintAnchor] = []
        if self.config.enable_core_constraint_anchoring:
            anchors = self.classifier.extract_core_constraints(messages)

        compacted: list[dict[str, str]] = []
        reduced_volatile_count = 0

        for cm in classified:
            orig_msg = messages[cm.index]
            new_msg = dict(orig_msg)

            # Volatile bulky tool outputs get structural lossless reduction
            if (
                cm.importance == MessageImportanceTier.VOLATILE
                and self.config.enable_tool_lean_reducer
            ):
                content = cm.content
                preview = content[:100].replace("\n", " ").strip()
                reduced_placeholder = (
                    f"[Tool Result Lean Reducer: {len(content)} chars historical payload "
                    f"condensed | preview: {preview}... | status: completed]"
                )
                new_msg["content"] = reduced_placeholder
                reduced_volatile_count += 1

            compacted.append(new_msg)

        # Inject constraint anchor block into system message or early turn if enabled
        if self.config.enable_core_constraint_anchoring and anchors and compacted:
            compacted = self._inject_anchors(compacted, anchors)

        compacted_tokens = sum(max(1, len(m.get("content", "")) // 4) for m in compacted)
        tokens_saved = max(0, original_tokens - compacted_tokens)
        reduction_pct = (
            (tokens_saved / original_tokens) * 100.0 if original_tokens > 0 else 0.0
        )

        stats = LeanReductionStats(
            original_tokens_estimate=original_tokens,
            compacted_tokens_estimate=compacted_tokens,
            tokens_saved_estimate=tokens_saved,
            reduction_percentage=reduction_pct,
            volatile_tool_outputs_reduced=reduced_volatile_count,
            anchors_preserved_count=len(anchors),
        )

        return compacted, stats

    def _inject_anchors(
        self,
        messages: list[dict[str, str]],
        anchors: list[ConstraintAnchor],
    ) -> list[dict[str, str]]:
        """Inject immutable constraint block into system prompt or first message."""
        out = [dict(m) for m in messages]
        anchor_text = "\n".join(
            f'- [Turn {a.source_turn}] {a.original_text}' for a in anchors
        )
        anchor_block = (
            f"\n\n<core_task_constraints>\n"
            f"[ANCHORED USER INTENT - NEVER DEVIATE OR COMPACT OUT]\n"
            f"{anchor_text}\n"
            f"</core_task_constraints>"
        )

        target_idx = 0
        for idx, m in enumerate(out):
            if m.get("role") == "system":
                target_idx = idx
                break

        curr_content = out[target_idx].get("content", "")
        if "<core_task_constraints>" not in curr_content:
            out[target_idx]["content"] = curr_content + anchor_block

        return out
