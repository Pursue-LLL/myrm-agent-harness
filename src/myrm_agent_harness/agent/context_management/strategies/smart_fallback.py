"""Smart fallback strategy for extreme token overflow scenarios.

When essential content (CRITICAL + HIGH priority) alone exceeds budget,
this module provides a fallback strategy to gracefully degrade compression.

Inspired by OpenSpace conversation_formatter.py:_assemble_essential_only
but adapted for our token-based architecture.

Fallback策略（当HIGH-priority内容超预算）：
1. 保留所有Priority 0 (human messages) 完整
2. Budget-allocate Priority 2 (tool calls/errors)
3. 一行摘要Priority 3 (reasoning)
4. 丢弃Priority 4 (success results)
5. Boundary Guard: 移除开头的孤儿 ToolMessage，防止不完整的工具调用对传递给 LLM

Boundary Guard 保护：
解决的问题：当Smart Fallback重建消息列表时，可能出现ToolMessage成为第一条消息
的情况（对应的AIMessage被判定为非CRITICAL而未保留）。这会导致LLM收到不完整
的工具调用对，产生困惑或错误响应。

实现：在返回前检查result_messages[0]，如果是ToolMessage则循环删除，直到找到
HumanMessage或AIMessage。这确保LLM始终收到语义完整的消息历史。

[INPUT]
- (none)

[OUTPUT]
- apply_smart_fallback: Apply smart fallback when essential content exceeds budget.

[POS]
Smart fallback strategy for extreme token overflow scenarios.
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from ..infra.message_priority import MessagePriority, classify_message_priority
from .compression_formatting import shrink_tool_call_args
from .integrity_guard import ensure_tool_pair_integrity
from .tool_call_groups import build_tool_call_groups

logger = get_agent_logger(__name__)


async def apply_smart_fallback(messages: list[BaseMessage], max_tokens: int) -> tuple[list[BaseMessage], int]:
    """Apply smart fallback when essential content exceeds budget.

    Args:
        messages: Original messages
        max_tokens: Maximum allowed tokens

    Returns:
        (Fallback messages, tokens saved)
    """
    logger.warning(f" Applying SMART FALLBACK: essential content exceeds {max_tokens} tokens")

    # Detect last iteration
    is_last_iteration = _detect_last_iteration_ids(messages)

    # Phase 1: Keep all CRITICAL (priority 0-1) messages
    critical_messages: list[tuple[int, BaseMessage]] = []
    for i, msg in enumerate(messages):
        priority = classify_message_priority(msg, is_last_iteration=is_last_iteration.get(id(msg), False))
        if priority <= MessagePriority.CRITICAL_FINAL:
            critical_messages.append((i, msg))

    result_messages: list[BaseMessage] = [msg for _, msg in critical_messages]
    used_tokens = estimate_messages_tokens(result_messages)

    if used_tokens >= max_tokens:
        logger.error(f" Even CRITICAL messages exceed budget ({used_tokens} >= {max_tokens})")
        return result_messages, 0

    remaining_budget = max_tokens - used_tokens

    # Phase 2: Budget-allocate HIGH priority tool pairs atomically
    high_group_indices: set[int] = set()
    high_groups = []
    for group in build_tool_call_groups(messages):
        ai_priority = classify_message_priority(
            group.ai_message, is_last_iteration=is_last_iteration.get(id(group.ai_message), False)
        )
        tool_priority = classify_message_priority(
            group.tool_message, is_last_iteration=is_last_iteration.get(id(group.tool_message), False)
        )
        if ai_priority in {MessagePriority.HIGH_TOOL_CALL, MessagePriority.HIGH_TOOL_ERROR} or tool_priority in {
            MessagePriority.HIGH_TOOL_CALL,
            MessagePriority.HIGH_TOOL_ERROR,
        }:
            high_groups.append(group)
            high_group_indices.update({group.ai_index, group.tool_index})

    if high_groups:
        per_group_budget = max(320, remaining_budget // (len(high_groups) + 1))
        for group in high_groups:
            ai_budget = max(120, per_group_budget // 3)
            tool_budget = max(200, per_group_budget - ai_budget)

            ai_message: BaseMessage = group.ai_message
            tool_message: BaseMessage = group.tool_message

            if estimate_messages_tokens([group.ai_message]) > ai_budget:
                ai_message = _truncate_ai_message(group.ai_message, ai_budget)
            if estimate_messages_tokens([group.tool_message]) > tool_budget:
                tool_message = _truncate_tool_message(group.tool_message, tool_budget)

            pair_tokens = estimate_messages_tokens([ai_message, tool_message])
            if used_tokens + pair_tokens > max_tokens:
                break

            result_messages.extend([ai_message, tool_message])
            used_tokens += pair_tokens

    # Phase 3: One-line summaries for MEDIUM priority (reasoning)
    if used_tokens < max_tokens:
        medium_messages: list[tuple[int, BaseMessage]] = []
        for i, msg in enumerate(messages):
            if i in {idx for idx, _ in critical_messages} or i in high_group_indices:
                continue
            priority = classify_message_priority(msg, is_last_iteration=is_last_iteration.get(id(msg), False))
            if priority == MessagePriority.MEDIUM_REASONING:
                medium_messages.append((i, msg))

        for _idx, msg in medium_messages:
            if isinstance(msg, AIMessage) and msg.content:
                # One-line summary (first 100 chars)
                summary = str(msg.content).split("\n")[0][:100]
                summary_msg = AIMessage(content=f"[Summarized] {summary}...")
                result_messages.append(summary_msg)
                used_tokens += estimate_messages_tokens([summary_msg])
                if used_tokens >= max_tokens:
                    break

    # Tool Integrity Guard: Ensure semantic completeness of tool call pairs
    # This prevents sending incomplete tool call sequences to the LLM
    result_messages = ensure_tool_pair_integrity(result_messages)

    # Calculate tokens saved
    original_tokens = estimate_messages_tokens(messages)
    tokens_saved = original_tokens - estimate_messages_tokens(result_messages)

    logger.warning(
        f" Smart fallback applied: kept {len(result_messages)}/{len(messages)} messages, saved {tokens_saved} tokens"
    )

    return result_messages, tokens_saved


def _detect_last_iteration_ids(messages: list[BaseMessage]) -> dict[int, bool]:
    """Detect which messages belong to last iteration."""
    last_human_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_human_idx = i
            break

    return {id(msg): i > last_human_idx if last_human_idx >= 0 else False for i, msg in enumerate(messages)}


def _truncate_tool_message(msg: ToolMessage, budget_tokens: int) -> ToolMessage:
    """Truncate tool message to fit budget."""
    content = str(msg.content)
    # Estimate ~4 chars per token
    max_chars = budget_tokens * 4
    if len(content) > max_chars:
        content = content[:max_chars] + f"... [budget-truncated, total {len(content)} chars]"

    return ToolMessage(content=content, tool_call_id=msg.tool_call_id)


def _truncate_ai_message(msg: AIMessage, budget_tokens: int) -> AIMessage:
    """Truncate AI message to fit budget.

    Shrinks both text content AND tool_call args to prevent oversized
    JSON arguments from causing API 400 errors after truncation.
    """
    content = str(msg.content) if msg.content else ""
    max_chars = budget_tokens * 4
    if len(content) > max_chars:
        content = content[:max_chars] + "... [budget-truncated]"

    tool_calls = shrink_tool_call_args(msg.tool_calls) if msg.tool_calls else msg.tool_calls

    return AIMessage(content=content, tool_calls=tool_calls)
