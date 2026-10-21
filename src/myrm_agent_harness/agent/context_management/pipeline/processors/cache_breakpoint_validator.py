"""Cache breakpoint validation — Anthropic/阿里云 cache_control 断点验证.

Validates breakpoints against provider constraints:
1. Dedup and sort
2. Filter invalid indices
3. Token distance enforcement (≥ 1024 tokens between breakpoints)
4. Max breakpoints limit (≤ 4 per Anthropic/阿里云)

All functions are pure — no side effects, no I/O.

[INPUT]
- (none)

[OUTPUT]
- dedup_and_sort: function — dedup_and_sort
- filter_invalid: function — filter_invalid
- enforce_max_breakpoints: function — enforce_max_breakpoints
- validate_token_distances: function — validate_token_distances
- validate_breakpoints: function — validate_breakpoints

[POS]
Validates breakpoints against provider constraints:
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from .cache_optimizer import ANTHROPIC_MIN_CACHEABLE_TOKENS

logger = get_agent_logger(__name__)


def dedup_and_sort(breakpoints: list[int]) -> list[int]:
    """去重并排序断点索引。"""
    return sorted(set(breakpoints))


def filter_invalid(breakpoints: list[int], messages: list[BaseMessage]) -> list[int]:
    """过滤无效的断点索引。"""
    return [idx for idx in breakpoints if 0 <= idx < len(messages)]


def enforce_max_breakpoints(breakpoints: list[int], messages: list[BaseMessage], max_breakpoints: int) -> list[int]:
    """限制断点数量不超过提供商限制

    Anthropic/阿里云限制：最多 4 个断点。

    智能保留策略：
    - 第一个（System）：永远保留 → 缓存系统提示词
    - 最后一个（最后消息）：永远保留 → 增量缓存核心（官方推荐）
    - 中间 N 个（保护断点）：保留前 (max_breakpoints - 2) 个
    """
    if len(breakpoints) <= max_breakpoints:
        return breakpoints

    last_msg_idx = len(messages) - 1
    has_last = breakpoints[-1] == last_msg_idx

    if has_last and len(breakpoints) >= 2:
        first_bp = breakpoints[0]
        last_bp = breakpoints[-1]
        middle_bps = breakpoints[1:-1]

        max_middle = max_breakpoints - 2
        middle_bps = middle_bps[:max_middle]

        result = [first_bp, *middle_bps, last_bp]

        logger.warning(
            f" [ExplicitCache] 断点数超限 ({len(breakpoints)} > {max_breakpoints})，"
            f"智能保留: System(#{first_bp}) + {len(middle_bps)}个保护断点 + 最后消息(#{last_bp})"
        )
        return result
    else:
        logger.warning(
            f" [ExplicitCache] 断点数超限 ({len(breakpoints)} > {max_breakpoints})，"
            f"保留前 {max_breakpoints} 个（注意：可能缺少最后消息断点）"
        )
        result = breakpoints[:max_breakpoints]

        logger.error(
            f" [ExplicitCache] 异常：最后消息断点未在验证列表中，"
            f"这可能导致增量缓存失效！breakpoints={breakpoints}, last_msg_idx={last_msg_idx}"
        )
        return result


def validate_token_distances(breakpoints: list[int], messages: list[BaseMessage], min_message_gap: int) -> list[int]:
    """验证断点间 token 距离

    Anthropic 要求：断点间至少 1024 tokens。

    特殊规则：
    - 最后消息断点无条件保留（增量缓存核心）
    - 非最后消息：优先检查 token 距离，fallback 到消息间隔
    """
    if not breakpoints:
        return []

    validated = [breakpoints[0]]
    last_msg_idx = len(messages) - 1

    for curr_bp in breakpoints[1:]:
        prev_bp = validated[-1]
        message_gap = curr_bp - prev_bp

        is_last_message = curr_bp == last_msg_idx

        segment_tokens = estimate_messages_tokens(messages[prev_bp : curr_bp + 1])

        if is_last_message:
            validated.append(curr_bp)
            if segment_tokens < ANTHROPIC_MIN_CACHEABLE_TOKENS:
                logger.debug(
                    f" [ExplicitCache] 最后消息断点 #{curr_bp} 距离较近 "
                    f"({segment_tokens} < {ANTHROPIC_MIN_CACHEABLE_TOKENS} tokens)，"
                    f"但仍保留（增量缓存核心）"
                )
        else:
            if segment_tokens >= ANTHROPIC_MIN_CACHEABLE_TOKENS:
                validated.append(curr_bp)
            elif message_gap >= min_message_gap:
                validated.append(curr_bp)
                logger.debug(
                    f" [ExplicitCache] 断点 #{curr_bp} token 不足 "
                    f"({segment_tokens} < {ANTHROPIC_MIN_CACHEABLE_TOKENS})，"
                    f"但消息间隔满足 ({message_gap} >= {min_message_gap})，保留"
                )
            else:
                logger.warning(
                    f" [ExplicitCache] 断点 #{curr_bp} 间隔过小 (tokens={segment_tokens}, messages={message_gap})，跳过"
                )

    return validated


def validate_breakpoints(
    breakpoints: list[int], messages: list[BaseMessage], min_message_gap: int, max_breakpoints: int
) -> list[int]:
    """验证断点是否符合提供商限制

    验证规则（基于 Anthropic 官方要求）：
    1. 去重并排序
    2. 过滤无效索引
    3. 检查断点间距离（≥ 1024 tokens）
    4. 限制最大数量（≤ 4 个）
    """
    if not breakpoints:
        return []

    breakpoints = dedup_and_sort(breakpoints)
    breakpoints = filter_invalid(breakpoints, messages)

    if not breakpoints:
        return []

    breakpoints = validate_token_distances(breakpoints, messages, min_message_gap)
    breakpoints = enforce_max_breakpoints(breakpoints, messages, max_breakpoints)

    return breakpoints
