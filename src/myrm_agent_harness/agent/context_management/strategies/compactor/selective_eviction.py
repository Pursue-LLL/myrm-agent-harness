"""Selective eviction engine based on working memory marks.

Performs fine-grained deterministic pruning and folding of transient messages
(such as single-turn hints and intermediate scratchpads) while maintaining strict
Tool Pair Invariant and whitelist immunity for pinned rules.

[INPUT]
- langchain_core.messages::AIMessage, BaseMessage, ToolMessage (POS: LangChain message contract)
- ...working_memory.marks::WorkingMemoryMark, get_message_marks, is_eviction_immune
- ..tool_call_groups::build_tool_call_groups (POS: atomic tool pair grouping)
- myrm_agent_harness.utils.text_utils::get_token_count (POS: Token counting)

[OUTPUT]
- SelectiveEvictionStats: dataclass recording evicted counts and token savings
- evict_messages_by_marks: function executing mark-driven safe eviction

[POS]
Deterministic selective compactor engine. Operates prior to destructive LLM summarization.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.tool_call_groups import (
    build_tool_call_groups,
)
from myrm_agent_harness.agent.context_management.working_memory.marks import (
    IMMUNE_MARKS,
    WorkingMemoryMark,
    get_message_marks,
    is_eviction_immune,
    remove_message_marks,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.text_utils import get_token_count

logger = get_agent_logger(__name__)

DEFAULT_TRANSIENT_MARKS: frozenset[str] = frozenset(
    {
        WorkingMemoryMark.HINT.value,
        WorkingMemoryMark.SCRATCHPAD.value,
    }
)


@dataclass(frozen=True, slots=True)
class SelectiveEvictionStats:
    """Telemetry snapshot of a selective eviction run."""

    evicted_count: int = 0
    tokens_saved: int = 0
    evicted_marks: tuple[str, ...] = ()
    immune_protected_count: int = 0
    tool_pairs_folded: int = 0


def _calculate_message_tokens(msg: BaseMessage) -> int:
    """Calculate approx token length of message content."""
    content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
    return get_token_count(content)


def evict_messages_by_marks(
    messages: Sequence[BaseMessage],
    target_marks: set[str] | frozenset[str] | None = None,
    preserve_marks: set[str] | frozenset[str] | None = None,
) -> tuple[list[BaseMessage], SelectiveEvictionStats]:
    """Prune or compact messages based on working memory marks with tool-pair safety.

    Rules:
    1. Immunity Guard: Messages with marks in IMMUNE_MARKS or preserve_marks are strictly kept.
    2. Tool Pair Invariant: If a ToolMessage is targeted for eviction/folding, its paired
       AIMessage tool_calls are atomically reconciled to avoid hanging tool call IDs (HTTP 400).
    3. Transient Message Eviction: Non-tool messages matching target_marks are safely removed.

    Args:
        messages: Input message sequence.
        target_marks: Marks to target for eviction. Defaults to HINT and SCRATCHPAD.
        preserve_marks: Extra marks to exempt from eviction.

    Returns:
        tuple of (retained_messages, stats).
    """
    effective_targets = target_marks if target_marks is not None else DEFAULT_TRANSIENT_MARKS
    extra_preserve = preserve_marks if preserve_marks is not None else frozenset()
    all_protected = IMMUNE_MARKS | extra_preserve

    if not messages or not effective_targets:
        return list(messages), SelectiveEvictionStats()

    # Step 1: Map tool call pairs to respect Tool Pair Invariant
    tool_groups = build_tool_call_groups(list(messages))
    tool_msg_to_group = {id(group.tool_message): group for group in tool_groups}

    evicted_count = 0
    tokens_saved = 0
    immune_protected_count = 0
    tool_pairs_folded = 0
    collected_marks: set[str] = set()

    retained: list[BaseMessage] = []

    for msg in messages:
        marks = get_message_marks(msg)

        # Rule 1: Check whitelist immunity
        if is_eviction_immune(msg) or bool(marks & all_protected):
            retained.append(msg)
            if bool(marks & all_protected):
                immune_protected_count += 1
            continue

        # Rule 2: Check if message matches target eviction marks
        matched_marks = marks & effective_targets
        if not matched_marks:
            retained.append(msg)
            continue

        # Target matched: handle ToolMessage vs Regular Message
        if isinstance(msg, ToolMessage):
            group = tool_msg_to_group.get(id(msg))
            if group is not None:
                # To maintain tool pair integrity, fold content rather than dropping message
                old_tokens = _calculate_message_tokens(msg)
                placeholder_content = f"[Folded tool output ({', '.join(sorted(matched_marks))})]"
                folded_msg = ToolMessage(
                    content=placeholder_content,
                    tool_call_id=msg.tool_call_id,
                    name=getattr(msg, "name", None),
                    additional_kwargs=dict(msg.additional_kwargs or {}),
                )
                remove_message_marks(folded_msg, *matched_marks)
                retained.append(folded_msg)
                saved = max(0, old_tokens - get_token_count(placeholder_content))
                tokens_saved += saved
                evicted_count += 1
                tool_pairs_folded += 1
                collected_marks.update(matched_marks)
            else:
                # Unpaired tool message, safe to drop
                tokens_saved += _calculate_message_tokens(msg)
                evicted_count += 1
                collected_marks.update(matched_marks)
        else:
            # Regular Human/AI/System transient message: safe to drop completely
            tokens_saved += _calculate_message_tokens(msg)
            evicted_count += 1
            collected_marks.update(matched_marks)

    stats = SelectiveEvictionStats(
        evicted_count=evicted_count,
        tokens_saved=tokens_saved,
        evicted_marks=tuple(sorted(collected_marks)),
        immune_protected_count=immune_protected_count,
        tool_pairs_folded=tool_pairs_folded,
    )

    if evicted_count > 0:
        logger.info(
            "[SelectiveEviction] Evicted %d messages (marks=%s, saved ~%d tokens, protected=%d, folded_tools=%d)",
            evicted_count,
            stats.evicted_marks,
            tokens_saved,
            immune_protected_count,
            tool_pairs_folded,
        )

    return retained, stats
