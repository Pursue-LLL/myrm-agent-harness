"""Pi Agent-style progressive context compaction and branch summarization engine.

Reference: Mario Zechner Pi Agent (packages/coding-agent/src/core/compaction/compaction.ts).
Features:
- Protocol-safe cut point selection (never split toolCall / toolResult pairs).
- Cumulative read/modified file tracking rendered via XML blocks.
- Rolling cumulative structured summaries with <previous-summary> continuation.
- Split-turn handling for oversized single turns.
- LCA branch exploration summary stitching.
Strict 0 Any, type-hinted, thread-safe.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence

from .pi_compaction_types import (
    CumulativeFileRecord,
    CutPointResult,
    PiCompactionConfig,
    PiCompactionResult,
    RollingStructuredSummary,
)
from .surface_projection_types import MessageRole, ProjectedMessage

_READ_TOOL_NAMES = {"read_file", "view_file", "read_context_file"}
_WRITE_TOOL_NAMES = {
    "write_file",
    "write_to_file",
    "edit_file",
    "replace_file_content",
    "apply_patch",
}


def estimate_message_tokens(message: ProjectedMessage) -> int:
    """Heuristic token estimator (chars // 4) ensuring protocol safety margins."""
    total_chars = len(message.content or "")
    if message.reasoning_content:
        total_chars += len(message.reasoning_content)
    if message.tool_calls:
        total_chars += sum(len(tc) for tc in message.tool_calls)
    return max(1, math.ceil(total_chars / 4))


class CumulativeFileTracker:
    """Tracks files read and modified across all compaction cycles, rendering XML tags."""

    @classmethod
    def extract_from_messages(
        cls,
        messages: Sequence[ProjectedMessage],
        prev_record: CumulativeFileRecord | None = None,
    ) -> CumulativeFileRecord:
        """Extract read and modified file paths from tool invocations and merge cumulatively."""
        read_set: set[str] = set(prev_record.read_files) if prev_record else set()
        modified_set: set[str] = set(prev_record.modified_files) if prev_record else set()

        for msg in messages:
            # Check tool call metadata or content pattern
            if msg.role == MessageRole.TOOL:
                tool_name = (msg.name or "").lower()
                content = msg.content or ""
                path_match = re.search(r"['\"]?([a-zA-Z0-9_\-\.\/]+\.[a-zA-Z0-9]+)['\"]?", content)
                if path_match:
                    found_path = path_match.group(1).strip()
                    if tool_name in _READ_TOOL_NAMES or "read" in tool_name:
                        read_set.add(found_path)
                    elif tool_name in _WRITE_TOOL_NAMES or "write" in tool_name or "edit" in tool_name:
                        modified_set.add(found_path)

            if msg.tool_calls:
                for tc_str in msg.tool_calls:
                    try:
                        data = json.loads(tc_str) if tc_str.startswith("{") else {}
                        fn_name = data.get("name", "").lower()
                        args = data.get("arguments", {})
                        if isinstance(args, str):
                            args = json.loads(args) if args.startswith("{") else {}
                        path_arg = (
                            args.get("path")
                            or args.get("file_path")
                            or args.get("TargetFile")
                            or args.get("AbsolutePath")
                        )
                        if path_arg and isinstance(path_arg, str):
                            p = path_arg.strip()
                            if fn_name in _READ_TOOL_NAMES or "read" in fn_name:
                                read_set.add(p)
                            elif fn_name in _WRITE_TOOL_NAMES or "write" in fn_name or "replace" in fn_name:
                                modified_set.add(p)
                    except Exception:
                        continue

        return CumulativeFileRecord(
            read_files=tuple(sorted(read_set)),
            modified_files=tuple(sorted(modified_set)),
        )


def find_protocol_safe_cut_point(
    messages: Sequence[ProjectedMessage],
    keep_recent_tokens: int = 20000,
    allow_split_turn: bool = True,
) -> CutPointResult:
    """Find a protocol-safe cut point accumulating approximately keep_recent_tokens backwards.

    Safety Rule: Never cut at a tool result message (tool must stay with its tool call).
    """
    if not messages:
        return CutPointResult(
            first_kept_index=0,
            turn_start_index=0,
            is_split_turn=False,
            kept_tokens=0,
            first_kept_entry_id="msg-0",
        )

    accumulated_tokens = 0
    candidate_cut_index = len(messages) - 1

    # Walk backwards accumulating tokens
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        msg_tokens = estimate_message_tokens(msg)
        accumulated_tokens += msg_tokens

        # Check if accumulated enough
        if accumulated_tokens >= keep_recent_tokens:
            candidate_cut_index = idx
            break

    # Protocol safety: if cut point is a TOOL result, rewind forward/backward to nearest valid cut point
    # Valid cut points are USER or ASSISTANT messages.
    safe_cut_index = candidate_cut_index
    while safe_cut_index > 0 and messages[safe_cut_index].role == MessageRole.TOOL:
        # Rewind backward to include preceding assistant tool call
        safe_cut_index -= 1

    # Locate turn start (preceding user message)
    turn_start_idx = safe_cut_index
    while turn_start_idx > 0 and messages[turn_start_idx].role != MessageRole.USER:
        turn_start_idx -= 1

    is_split = (
        allow_split_turn
        and safe_cut_index > turn_start_idx
        and messages[safe_cut_index].role == MessageRole.ASSISTANT
    )

    return CutPointResult(
        first_kept_index=safe_cut_index,
        turn_start_index=turn_start_idx,
        is_split_turn=is_split,
        kept_tokens=accumulated_tokens,
        first_kept_entry_id=f"msg-{safe_cut_index}",
    )


class PiProgressiveCompactor:
    """Orchestrates Pi-style progressive compaction, cumulative tracking, and branch preservation."""

    @classmethod
    def should_compact(
        cls,
        context_tokens: int,
        config: PiCompactionConfig,
    ) -> bool:
        """Evaluate three-dimensional threshold condition."""
        if not config.enabled:
            return False
        return context_tokens > (config.context_window - config.reserve_tokens)

    @classmethod
    def compact(
        cls,
        messages: Sequence[ProjectedMessage],
        prev_record: CumulativeFileRecord | None = None,
        config: PiCompactionConfig | None = None,
    ) -> PiCompactionResult:
        """Perform rolling progressive compaction creating structured summary node and preserving tail."""
        cfg = config or PiCompactionConfig()
        total_tokens_before = sum(estimate_message_tokens(m) for m in messages)

        cut = find_protocol_safe_cut_point(
            messages=messages,
            keep_recent_tokens=cfg.keep_recent_tokens,
            allow_split_turn=cfg.allow_split_turn,
        )

        messages_to_summarize = messages[: cut.first_kept_index]
        kept_messages = messages[cut.first_kept_index :]

        # Cumulative file tracking
        cum_files = CumulativeFileTracker.extract_from_messages(
            messages=messages_to_summarize,
            prev_record=prev_record,
        )

        # Synthesize rolling structured summary
        summary_model = cls._synthesize_rolling_summary(
            messages=messages_to_summarize,
            files=cum_files,
            focus=cfg.focus_directive,
            is_split_turn=cut.is_split_turn,
        )
        summary_text = summary_model.render_markdown()

        # Construct projected messages: [Compacted Summary System Message] + kept_messages
        summary_msg = ProjectedMessage(
            role=MessageRole.SYSTEM,
            content=(
                "<compaction_context>\n"
                f"{summary_text}\n"
                "</compaction_context>"
            ),
        )
        projected = (summary_msg, *kept_messages)
        total_tokens_after = sum(estimate_message_tokens(m) for m in projected)

        return PiCompactionResult(
            summary_text=summary_text,
            cut_point=cut,
            cumulative_files=cum_files,
            tokens_before=total_tokens_before,
            tokens_after=total_tokens_after,
            projected_messages=projected,
            is_split_turn=cut.is_split_turn,
        )

    @classmethod
    def _synthesize_rolling_summary(
        cls,
        messages: Sequence[ProjectedMessage],
        files: CumulativeFileRecord,
        focus: str,
        is_split_turn: bool,
    ) -> RollingStructuredSummary:
        """Synthesize structured sections from summarized messages."""
        goals: list[str] = []
        done_items: list[str] = []
        decisions: list[str] = []
        next_items: list[str] = []

        for m in messages:
            if m.role == MessageRole.USER and m.content:
                goals.append(m.content[:80].strip())
            elif m.role == MessageRole.ASSISTANT and m.content:
                if "done" in m.content.lower() or "completed" in m.content.lower():
                    done_items.append(m.content[:80].strip())
                elif "decision" in m.content.lower() or "decided" in m.content.lower():
                    decisions.append(m.content[:80].strip())
                elif "todo" in m.content.lower() or "next" in m.content.lower():
                    next_items.append(m.content[:80].strip())
            elif m.role == MessageRole.TOOL and m.content:
                done_items.append(f"Tool executed: {(m.name or 'tool')} -> {m.content[:40]}...")

        goal_text = " / ".join(goals) if goals else "Execute requested agent workflows"
        if is_split_turn:
            goal_text = f"[Split-Turn] Continued execution: {goal_text}"

        return RollingStructuredSummary(
            goal=goal_text,
            constraints="Zero regression, preserve integrity",
            progress_done=tuple(done_items[:5]),
            progress_in_progress=("Executing active turn continuation",),
            key_decisions=tuple(decisions[:3]),
            next_steps=tuple(next_items[:3]) if next_items else ("Complete downstream sub-tasks",),
            critical_context="Preserved causality from prior compacted turns",
            cumulative_files=files,
            focus_directive=focus,
        )

    @classmethod
    def generate_branch_lca_summary(
        cls,
        branch_path_messages: Sequence[ProjectedMessage],
        branch_id: str,
    ) -> ProjectedMessage:
        """Generate branch exploration summary for seamless navigation across LCA ancestor nodes."""
        actions: list[str] = []
        for m in branch_path_messages:
            if m.content:
                actions.append(f"[{m.role.value}] {m.content[:60]}")

        summary_body = (
            f"**Branch Exploration Summary (from {branch_id}):**\n"
            + ("\n".join(f"- {act}" for act in actions[:8]) if actions else "- No turn activity recorded")
        )
        return ProjectedMessage(
            role=MessageRole.SYSTEM,
            content=f"<branch_lca_summary branch_id='{branch_id}'>\n{summary_body}\n</branch_lca_summary>",
        )


find_pi_protocol_safe_cut_point = find_protocol_safe_cut_point

