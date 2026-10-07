"""Transient tool output garbage collection engine.

Identifies obsolete intermediate diagnostic, grep, and exploratory logs from
earlier conversation turns and dehydrates them into compact single-line receipts,
eliminating compound Token Tax while preserving causal execution provenance.

[INPUT]
- runtime.context.universal_thin_harness_types::TransientToolOutputGCReceipt (POS: Universal agent thin
  harness adaptive contract and Token Tax governor types.)

[OUTPUT]
- TransientToolOutputGCEngine: Collects and dehydrates transient intermediate tool outputs in multi-turn
  contexts.

[POS]
Transient tool output garbage collection engine.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .universal_thin_harness_types import TransientToolOutputGCReceipt


class TransientToolOutputGCEngine:
    """Collects and dehydrates transient intermediate tool outputs in multi-turn contexts."""

    def __init__(
        self,
        dehydration_char_threshold: int = 300,
        keep_recent_turns: int = 2,
        chars_per_token_ratio: float = 3.8,
    ) -> None:
        self._threshold = dehydration_char_threshold
        self._keep_recent = keep_recent_turns
        self._chars_per_token_ratio = chars_per_token_ratio

    def estimate_tokens(self, text: str) -> int:
        """Estimates token count deterministically from string length."""
        if not text.strip():
            return 0
        return max(1, math.ceil(len(text) / self._chars_per_token_ratio))

    def dehydrate_turn_history(
        self,
        messages: Sequence[dict[str, str]],
    ) -> tuple[list[dict[str, str]], tuple[TransientToolOutputGCReceipt, ...]]:
        """Processes message sequence and dehydrates eligible past tool outputs."""
        if not messages:
            return [], ()

        total_msgs = len(messages)
        cutoff_index = max(0, total_msgs - self._keep_recent)

        processed_messages: list[dict[str, str]] = []
        receipts: list[TransientToolOutputGCReceipt] = []

        for idx, msg in enumerate(messages):
            msg_copy = dict(msg)
            role = msg_copy.get("role", "")
            content = msg_copy.get("content", "")
            tool_name = msg_copy.get("name", "tool")
            msg_id = msg_copy.get("id", f"msg_{idx:03d}")

            # Only tool outputs occurring before recent cutoff are candidates for dehydration
            is_tool_role = role in ("tool", "tool_result", "observation")
            if not is_tool_role or idx >= cutoff_index:
                processed_messages.append(msg_copy)
                continue

            orig_len = len(content)
            if orig_len <= self._threshold:
                # Content already below threshold, keep verbatim
                processed_messages.append(msg_copy)
                continue

            # Perform dehydration into compact summary receipt
            first_line = content.strip().splitlines()[0] if content.strip() else "completed"
            snippet = first_line[:60].strip()
            line_count = len(content.splitlines())

            dehydrated_text = (
                f"[Tool Output Dehydrated: tool={tool_name} | status=resolved | "
                f"lines={line_count} | preview='{snippet}...' | preserved in telemetry]"
            )

            dehydrated_len = len(dehydrated_text)
            orig_tokens = self.estimate_tokens(content)
            new_tokens = self.estimate_tokens(dehydrated_text)
            saved = max(0, orig_tokens - new_tokens)

            msg_copy["content"] = dehydrated_text
            msg_copy["is_dehydrated"] = "true"
            processed_messages.append(msg_copy)

            receipts.append(
                TransientToolOutputGCReceipt(
                    message_id=msg_id,
                    tool_name=tool_name,
                    original_char_count=orig_len,
                    dehydrated_char_count=dehydrated_len,
                    saved_tokens=saved,
                    is_dehydrated=True,
                    reason=f"exceeded_threshold_{self._threshold}_in_past_turn",
                )
            )

        return processed_messages, tuple(receipts)
