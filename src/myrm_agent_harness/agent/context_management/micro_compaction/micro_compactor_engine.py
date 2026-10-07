"""Core implementation of Micro-Compaction and Amortized Turn Context Reclamation Engine.

Implements incremental per-turn exchange folding into a single running summary,
strict user prompt verbatim preservation, three-zone boundary protection,
and tokenomics-aware defrag and 3-strike failure skip governors.
"""

from __future__ import annotations

import threading
from typing import Callable

from .micro_compaction_types import (
    ExchangeBlock,
    MicroCompactionConfig,
    MicroCompactionResult,
    RunningSummaryState,
)


class MicroCompactorEngine:
    """Industrial engine for smooth, amortized turn context reclamation."""

    RUNNING_SUMMARY_TAG: str = "<running_context_summary>"

    def __init__(self, config: MicroCompactionConfig | None = None) -> None:
        self.config = config or MicroCompactionConfig()
        self._lock = threading.Lock()
        self._summaries: dict[str, RunningSummaryState] = {}
        self._failure_strikes: dict[str, dict[str, int]] = {}

    def get_running_summary(self, session_id: str) -> RunningSummaryState | None:
        """Retrieve current running summary state for a session."""
        with self._lock:
            return self._summaries.get(session_id)

    def should_trigger(self, current_turn_index: int) -> bool:
        """Evaluate cadence governor based on turn step to preserve prefix cache."""
        if current_turn_index <= (
            self.config.head_protected_turns + self.config.tail_protected_turns
        ):
            return False
        return (current_turn_index % self.config.compact_every_n_turns) == 0

    def compact_turn_instalment(
        self,
        session_id: str,
        current_turn_index: int,
        messages: list[dict[str, str]],
        custom_summarizer: Callable[[str, ExchangeBlock], str] | None = None,
    ) -> tuple[list[dict[str, str]], MicroCompactionResult]:
        """Execute a single instalment of micro-compaction on the oldest unabsorbed exchange."""
        with self._lock:
            running_summary = self._summaries.get(
                session_id,
                RunningSummaryState(
                    session_id=session_id,
                    summary_text="",
                    absorbed_exchanges_count=0,
                    last_absorbed_turn_index=-1,
                    defrag_count=0,
                    estimated_summary_tokens=0,
                ),
            )

            # Check cadence
            if not self.should_trigger(current_turn_index):
                return list(messages), MicroCompactionResult(
                    session_id=session_id,
                    is_compacted=False,
                    absorbed_exchange_id=None,
                    running_summary=running_summary,
                    reclaimed_chars=0,
                    diagnostics="Cadence threshold or protected zone guard active; skipped.",
                )

            # Partition conversation into turns by user messages
            turns_data = self._partition_turns(messages)
            total_turns = len(turns_data)

            # Middle zone: must be strictly between head and tail
            head_boundary = self.config.head_protected_turns
            tail_boundary = total_turns - self.config.tail_protected_turns

            if tail_boundary <= head_boundary:
                return list(messages), MicroCompactionResult(
                    session_id=session_id,
                    is_compacted=False,
                    absorbed_exchange_id=None,
                    running_summary=running_summary,
                    reclaimed_chars=0,
                    diagnostics="No middle zone available between head and tail boundaries.",
                )

            # Find the oldest unabsorbed exchange in the middle zone
            session_strikes = self._failure_strikes.setdefault(session_id, {})
            target_turn_idx: int | None = None
            target_exchange: ExchangeBlock | None = None

            for t_idx in range(head_boundary, tail_boundary):
                t_block = turns_data[t_idx]
                ex_id = f"exchange-turn-{t_idx}"
                strikes = session_strikes.get(ex_id, 0)
                if strikes >= self.config.max_retries_per_exchange:
                    continue  # 3-strike failure skip: advance cursor
                if t_idx > running_summary.last_absorbed_turn_index:
                    target_turn_idx = t_idx
                    target_exchange = self._build_exchange_block(ex_id, t_idx, t_block)
                    break

            if target_turn_idx is None or target_exchange is None:
                return list(messages), MicroCompactionResult(
                    session_id=session_id,
                    is_compacted=False,
                    absorbed_exchange_id=None,
                    running_summary=running_summary,
                    reclaimed_chars=0,
                    diagnostics="No eligible unabsorbed exchanges in middle zone.",
                )

            # Perform amortized folding
            try:
                new_summary_text = self._fold_exchange(
                    running_summary.summary_text, target_exchange, custom_summarizer
                )
            except Exception as exc:
                session_strikes[target_exchange.exchange_id] = (
                    session_strikes.get(target_exchange.exchange_id, 0) + 1
                )
                return list(messages), MicroCompactionResult(
                    session_id=session_id,
                    is_compacted=False,
                    absorbed_exchange_id=target_exchange.exchange_id,
                    running_summary=running_summary,
                    reclaimed_chars=0,
                    skipped_due_to_strikes=False,
                    diagnostics=f"Summarization failed ({exc}); strike recorded.",
                )

            # Check defrag threshold (tokens estimated at ~4 chars per token)
            defrag_count = running_summary.defrag_count
            est_tokens = len(new_summary_text) // 4
            if est_tokens > self.config.max_running_summary_tokens:
                new_summary_text = self._defrag_summary(new_summary_text)
                defrag_count += 1
                est_tokens = len(new_summary_text) // 4

            updated_summary = RunningSummaryState(
                session_id=session_id,
                summary_text=new_summary_text,
                absorbed_exchanges_count=running_summary.absorbed_exchanges_count + 1,
                last_absorbed_turn_index=target_turn_idx,
                defrag_count=defrag_count,
                estimated_summary_tokens=est_tokens,
            )
            self._summaries[session_id] = updated_summary

            # Reconstruct transcript: User prompts 100% preserved, single running summary tag
            reconstructed_messages, reclaimed_chars = self._reconstruct_messages(
                messages, turns_data, target_turn_idx, updated_summary.summary_text
            )

            return reconstructed_messages, MicroCompactionResult(
                session_id=session_id,
                is_compacted=True,
                absorbed_exchange_id=target_exchange.exchange_id,
                running_summary=updated_summary,
                reclaimed_chars=reclaimed_chars,
                diagnostics=f"Successfully absorbed turn {target_turn_idx} into running summary.",
            )

    def _partition_turns(
        self, messages: list[dict[str, str]]
    ) -> list[list[dict[str, str]]]:
        """Group messages into turns based on user message boundaries, ignoring system markers."""
        turns: list[list[dict[str, str]]] = []
        current_turn: list[dict[str, str]] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system" or self.RUNNING_SUMMARY_TAG in content:
                continue

            if role == "user":
                if current_turn:
                    turns.append(current_turn)
                current_turn = [msg]
            else:
                if current_turn:
                    current_turn.append(msg)

        if current_turn:
            turns.append(current_turn)
        return turns

    def _build_exchange_block(
        self, exchange_id: str, turn_index: int, turn_messages: list[dict[str, str]]
    ) -> ExchangeBlock:
        """Extract assistant narrative and tool outputs from a turn."""
        assistant_content: str | None = None
        tool_contents: list[str] = []
        total_chars = 0

        for msg in turn_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "assistant" and assistant_content is None:
                assistant_content = content
                total_chars += len(content)
            elif role in ("tool", "function") or "tool" in role:
                tool_contents.append(content)
                total_chars += len(content)

        return ExchangeBlock(
            exchange_id=exchange_id,
            turn_index=turn_index,
            assistant_content=assistant_content,
            tool_contents=tuple(tool_contents),
            total_chars=total_chars,
        )

    def _fold_exchange(
        self,
        existing_summary: str,
        exchange: ExchangeBlock,
        custom_summarizer: Callable[[str, ExchangeBlock], str] | None,
    ) -> str:
        """Fold an exchange into existing summary using callback or deterministic condensation."""
        if custom_summarizer is not None:
            return custom_summarizer(existing_summary, exchange)

        addition = f"[Turn {exchange.turn_index}]: "
        if exchange.assistant_content:
            short_asst = exchange.assistant_content.strip()
            addition += f"Assistant executed: {short_asst[:120]}... "
        if exchange.tool_contents:
            addition += f"Tools called ({len(exchange.tool_contents)} steps)."

        if not existing_summary.strip():
            return addition.strip()
        return f"{existing_summary.strip()}\n- {addition.strip()}"

    def _defrag_summary(self, summary_text: str) -> str:
        """Defragment and condense a running summary when exceeding token budget."""
        lines = [line.strip() for line in summary_text.splitlines() if line.strip()]
        if len(lines) <= 2:
            return summary_text
        condensed = [
            lines[0],
            f"... [Defragged {len(lines) - 2} prior intermediate notes] ...",
            lines[-1],
        ]
        return "\n".join(condensed)

    def _reconstruct_messages(
        self,
        original_messages: list[dict[str, str]],
        turns_data: list[list[dict[str, str]]],
        absorbed_turn_idx: int,
        summary_text: str,
    ) -> tuple[list[dict[str, str]], int]:
        """Reconstruct message sequence preserving all user prompts and updating single summary marker."""
        reconstructed: list[dict[str, str]] = []
        reclaimed_chars = 0
        summary_inserted = False

        summary_marker = {
            "role": "system",
            "content": f"{self.RUNNING_SUMMARY_TAG}\n{summary_text}\n</running_context_summary>",
        }

        # Handle system prompt at head
        idx = 0
        while idx < len(original_messages) and original_messages[idx].get("role") == "system":
            sys_msg = original_messages[idx]
            # Replace existing running summary if present, do not duplicate
            if self.RUNNING_SUMMARY_TAG in sys_msg.get("content", ""):
                pass  # will re-insert unified summary below
            else:
                reconstructed.append(sys_msg)
            idx += 1

        # Insert unified running summary directly after system prompt
        reconstructed.append(summary_marker)
        summary_inserted = True

        # Traverse turns: Head, absorbed turns, unabsorbed middle turns, and Tail
        for t_idx, t_msgs in enumerate(turns_data):
            if t_idx <= absorbed_turn_idx:
                # This turn has been absorbed: keep user prompt verbatim, strip assistant and tools
                for msg in t_msgs:
                    if msg.get("role") == "user":
                        reconstructed.append(msg)
                    else:
                        # Reclaimed assistant narrative & tool output
                        reclaimed_chars += len(msg.get("content", ""))
            else:
                # Unabsorbed middle or protected tail: preserve all messages completely
                for msg in t_msgs:
                    # Ignore old summary markers if present in message stream
                    if self.RUNNING_SUMMARY_TAG in msg.get("content", ""):
                        continue
                    reconstructed.append(msg)

        return reconstructed, reclaimed_chars
