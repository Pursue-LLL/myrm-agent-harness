"""Message importance classifier for categorizing conversation turns by criticality.

Tags messages into CRITICAL, HIGH, MEDIUM, and VOLATILE tiers to guide
lossless compression and prevent forgetting user requirements.

[INPUT]
- runtime.context.lossless_lean_tail_types::ClassifiedMessage, ConstraintAnchor, LosslessCompactorConfig,
  MessageImportanceTier (POS: Data types and schemas for default lossless lean-tail conversation
  compaction.)

[OUTPUT]
- MessageImportanceClassifier: Classifies conversation messages by structural and semantic importance.

[POS]
Message importance classifier for categorizing conversation turns by criticality.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.lossless_lean_tail_types import (
    ClassifiedMessage,
    ConstraintAnchor,
    LosslessCompactorConfig,
    MessageImportanceTier,
)


class MessageImportanceClassifier:
    """Classifies conversation messages by structural and semantic importance."""

    def __init__(self, config: LosslessCompactorConfig | None = None) -> None:
        self.config = config or LosslessCompactorConfig()

    def classify_messages(
        self, messages: list[dict[str, str]]
    ) -> list[ClassifiedMessage]:
        """Classify each message in sequence into an importance tier."""
        classified: list[ClassifiedMessage] = []
        n = len(messages)
        first_user_seen = False
        protected_threshold_idx = max(0, n - (self.config.protected_recent_turns * 2))

        for idx, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            token_est = max(1, len(content) // 4)

            is_tool_call = "tool_calls" in msg or "<tool_call>" in content
            is_tool_result = (
                role in ("tool", "function")
                or "tool_call_id" in msg
                or msg.get("name") is not None
            )

            tier: MessageImportanceTier

            # Rule 1: System prompt is always CRITICAL
            if role == "system":
                tier = MessageImportanceTier.CRITICAL

            # Rule 2: First user prompt is CRITICAL if preserve flag is on
            elif role == "user" and not first_user_seen and self.config.always_preserve_initial_user_prompt:
                tier = MessageImportanceTier.CRITICAL
                first_user_seen = True

            # Rule 3: Recent turns are protected as HIGH
            elif idx >= protected_threshold_idx:
                tier = MessageImportanceTier.HIGH

            # Rule 4: Bulky tool results in older turns are VOLATILE
            elif is_tool_result and len(content) >= self.config.tool_output_length_threshold:
                tier = MessageImportanceTier.VOLATILE

            # Rule 5: Standard turns are MEDIUM
            else:
                tier = MessageImportanceTier.MEDIUM

            classified.append(
                ClassifiedMessage(
                    index=idx,
                    role=role,
                    content=content,
                    importance=tier,
                    is_tool_call=is_tool_call,
                    is_tool_result=is_tool_result,
                    token_estimate=token_est,
                )
            )

        return classified

    def extract_core_constraints(
        self, messages: list[dict[str, str]]
    ) -> list[ConstraintAnchor]:
        """Extract immutable initial constraints from early user instructions."""
        anchors: list[ConstraintAnchor] = []
        for idx, msg in enumerate(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "").strip()
                if content:
                    anchors.append(
                        ConstraintAnchor(
                            anchor_id=f"anchor_user_turn_{idx}",
                            original_text=content[:500],
                            source_turn=idx,
                            tags={"initial_goal", "user_prompt"},
                        )
                    )
                # We primarily anchor the primary initial directive
                break
        return anchors
