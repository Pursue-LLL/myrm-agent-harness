"""Priority-aware message compactor.

Compresses older tool-call pairs with deterministic rules, optional offload,
deduplication, priority classification, and token-savings metrics.

[INPUT]
- langchain_core.messages::AIMessage, BaseMessage, ToolMessage (POS: LangChain 消息类型)
- utils.text_utils::get_token_count (POS: Token 计数工具)
- schemas::CompactToolCall, ContextConfig, ContextOffloadResult, EvictedToolCall (POS: 上下文配置与数据结构)
- token_estimation::estimate_messages_tokens (POS: Token 估算)
- compact_rules::COMPACT_RULES (POS: 压缩规则)
- message_priority::classify_message_priority (POS: 优先级分类)

[OUTPUT]
- should_compress(): 判断是否需要压缩(基于 token 阈值)
- compress_messages_async(): 压缩消息列表(Priority-aware三级策略;注意:Smart fallback在compress_processor层)
- compress_tool_message_async(): 压缩单个工具消息(可选 ContextCompressOffloadCallback)
- find_tool_message_pairs(): 基于 tool_call_id 找到完整工具调用对

[POS]
Message compactor. Priority-aware compression strategy with structured offload result handling for critical, important, and standard messages.

"""

import asyncio
import json
from datetime import datetime
from typing import cast

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.messages.tool import ToolCall

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.text_utils import get_token_count
from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from ..infra.message_priority import MessagePriority, classify_message_priority
from ..infra.schemas import (
    CompactToolCall,
    ContextCompressEvictionCallback,
    ContextCompressOffloadCallback,
    ContextConfig,
    ContextOffloadResult,
    EvictedToolCall,
    normalize_context_offload_result,
)
from .compact_rules import COMPACT_RULES
from .compression_formatting import (
    extract_identifier,
    generate_compressed_content,
    generate_compressed_content_with_stats,
    generate_generic_compressed_content,
    shrink_tool_call_args,
)
from .deduplication import deduplicate_tool_results
from .priority_signals import adjust_group_priority
from .tool_call_groups import build_tool_call_groups
from .tool_stats import extract_tool_stats

logger = get_agent_logger(__name__)
_file_tracking_tasks: set[asyncio.Task[None]] = set()

# 落盘阈值:工具输出 >= 此值时写入文件,< 此值时纯内存压缩
# 5000 tokens ≈ 20KB 文本
OFFLOAD_THRESHOLD_TOKENS = 5000


def should_compress(messages: list[BaseMessage], config: ContextConfig | None = None) -> bool:
    """判断是否需要压缩

    Args:
        messages: 消息列表
        config: 上下文配置(可选,默认使用 128k 窗口)

    Returns:
        是否需要压缩
    """
    from ..infra.schemas import DEFAULT_CONTEXT_CONFIG

    cfg = config or DEFAULT_CONTEXT_CONFIG
    total_tokens = estimate_messages_tokens(messages)
    return total_tokens >= cfg.compress_threshold


def _detect_last_iteration(messages: list[BaseMessage]) -> dict[int, bool]:
    """Detect which messages belong to the last iteration.

    Returns:
        Dict mapping message id() to is_last_iteration boolean
    """
    from langchain_core.messages import HumanMessage

    # Find last human message index
    last_human_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_human_idx = i
            break

    # Messages after last human are in final iteration
    result: dict[int, bool] = {}
    for i, msg in enumerate(messages):
        result[id(msg)] = i > last_human_idx if last_human_idx >= 0 else False

    return result


def find_tool_message_pairs(messages: list[BaseMessage]) -> list[tuple[int, int, AIMessage, ToolMessage]]:
    """找到所有工具调用对(AIMessage + ToolMessage)

    Args:
        messages: 消息列表

    Returns:
        工具调用对列表:[(ai_idx, tool_idx, ai_msg, tool_msg), ...]
    """
    return [
        (group.ai_index, group.tool_index, group.ai_message, group.tool_message)
        for group in build_tool_call_groups(messages)
    ]


async def compress_messages_async(
    messages: list[BaseMessage],
    dynamic_min_save: int | None = None,
    config: ContextConfig | None = None,
    *,
    on_compress_offload: ContextCompressOffloadCallback | None = None,
    on_compress_eviction: ContextCompressEvictionCallback | None = None,
    chat_id: str | None = None,
    user_id: str | None = None,
    failed_tool_call_ids: frozenset[str] | None = None,
    focus_files: frozenset[str] | None = None,
    focus_modules: frozenset[str] | None = None,
    user_goal_hint: str = "",
) -> tuple[list[BaseMessage], int]:
    """压缩消息列表中的旧工具调用

    四级压缩策略(增强版,参考Hermes):
    L0 Deduplicate: 去重重复内容(参考Hermes)
    L1 Dedup: 跳过已压缩内容
    L2 Truncate: 超大输出截断保留头尾 + 摘要
    L3 Remove: 替换为紧凑格式(工具标识符 + 元信息)

    Args:
        messages: 原始消息列表
        dynamic_min_save: 动态计算的最小节省阈值(可选,由调用方根据上下文预算传入)
        config: 上下文配置(可选,默认使用 128k 窗口)
        on_compress_offload: 压缩前落盘回调(可选,由业务层注入)
        on_compress_eviction: 压缩时触发提取记忆的回调(可选,由业务层注入)
        chat_id: 会话 ID(传入回调)
        user_id: 用户 ID(仅用于兼容上层调用; 不会传入归档回调)
        failed_tool_call_ids: 应优先保护的失败工具调用 ID
        focus_files: 当前任务聚焦的文件路径
        focus_modules: 当前任务聚焦的模块路径
        user_goal_hint: 当前任务的文本目标提示

    Returns:
        (压缩后的消息列表, 节省的 token 数)
    """
    from ..infra.schemas import DEFAULT_CONTEXT_CONFIG

    cfg = config or DEFAULT_CONTEXT_CONFIG

    # 【新增】L0: 去重重复内容(参考Hermes)
    messages, dedup_saved = deduplicate_tool_results(messages, cfg)

    groups = build_tool_call_groups(messages)
    total_declared_tool_calls = sum(
        len(msg.tool_calls) for msg in messages if isinstance(msg, AIMessage) and msg.tool_calls
    )
    unmatched_tool_calls = max(0, total_declared_tool_calls - len(groups))
    if unmatched_tool_calls > 0:
        logger.warning("[压缩] 检测到 %d 个未完整配对的 tool_call,已自动排除在压缩计划之外", unmatched_tool_calls)

    # P0: Priority-aware filtering - skip CRITICAL messages
    # Classify all messages by priority (is_last_iteration detection)
    is_last_iteration_msg = _detect_last_iteration(messages)
    message_priorities = [
        classify_message_priority(
            msg, is_last_iteration=is_last_iteration_msg.get(id(msg), False), failed_tool_call_ids=failed_tool_call_ids
        )
        for msg in messages
    ]

    # Filter pairs: only compress pairs where tool message is not CRITICAL
    compressible_groups = [
        group for group in groups if message_priorities[group.tool_index] > MessagePriority.CRITICAL_FINAL
    ]

    if len(compressible_groups) <= cfg.keep_recent_calls:
        logger.warning(f"[压缩] 可压缩工具调用数 ({len(compressible_groups)}) <= 保留数 ({cfg.keep_recent_calls}),跳过")
        return messages, 0

    # 计算需要压缩的数量(保留最近 N 个)
    num_to_compress = len(compressible_groups) - cfg.keep_recent_calls

    if num_to_compress <= 0:
        return messages, 0

    # Priority-based sorting: compress LOW priority (larger value) first
    groups_with_priority = [
        (
            group,
            adjust_group_priority(
                message_priorities[group.tool_index],
                group,
                focus_files=focus_files,
                focus_modules=focus_modules,
                user_goal_hint=user_goal_hint,
            ),
        )
        for group in compressible_groups
    ]
    # Sort by priority value DESC (4=LOW compressed first), then by index ASC (older first)
    groups_with_priority.sort(key=lambda x: (-x[1], x[0].tool_index))

    # Compress lowest priority pairs first
    groups_to_compress = [entry[0] for entry in groups_with_priority[:num_to_compress]]

    # 预计算节省的 token 数
    potential_saved = 0
    for group in groups_to_compress:
        tool_msg = group.tool_message
        if _is_already_compressed(tool_msg):
            continue
        content = tool_msg.content if isinstance(tool_msg.content, str) else json.dumps(tool_msg.content)
        potential_saved += get_token_count(content)

    # 使用动态阈值(如果提供),否则使用配置的静态阈值
    min_save_threshold = dynamic_min_save if dynamic_min_save is not None else cfg.compress_min_save

    # 检查是否值得压缩(避免破坏 Prompt Cache)
    if potential_saved < min_save_threshold:
        logger.warning(f"[压缩] 预计节省 ({potential_saved}) < 最小阈值 ({min_save_threshold}),跳过")
        return messages, 0

    # 执行压缩(无需保护,压缩是可逆的)
    total_saved = 0
    compressed_count = 0
    evicted_pairs: list[EvictedToolCall] = []
    offload_results: list[ContextOffloadResult] = []

    for group in groups_to_compress:
        tool_msg = group.tool_message
        ai_msg = group.ai_message

        if not _is_already_compressed(tool_msg):
            original_content = tool_msg.content if isinstance(tool_msg.content, str) else json.dumps(tool_msg.content)
            original_tokens = get_token_count(original_content)
            if original_tokens >= 500 and ai_msg:
                evicted_pairs.append(
                    EvictedToolCall(ai_msg=ai_msg, tool_msg=tool_msg, original_content=original_content)
                )

        saved = await compress_tool_message_async(
            tool_msg,
            ai_msg,
            on_offload=on_compress_offload,
            chat_id=chat_id,
            user_id=user_id,
            offload_results=offload_results,
        )
        if saved > 0:
            total_saved += saved
            compressed_count += 1

    if on_compress_eviction and evicted_pairs:
        try:
            await on_compress_eviction(evicted_pairs, user_goal_hint)
        except Exception as exc:
            logger.warning("[压缩] batch eviction extraction failed: %s", exc)

    if compressed_count > 0:
        logger.warning(f" [压缩] 压缩 {compressed_count} 个工具调用组,节省 ~{total_saved} tokens")

    # Record compression output and archive write/reuse telemetry in one event.
    final_saved = total_saved + dedup_saved
    _record_compression_to_metrics(
        final_saved,
        "compress",
        f"Compressed {compressed_count} tool call groups "
        f"(dedup: {dedup_saved} tokens, integrity_skipped: {unmatched_tool_calls})",
        group_count=compressed_count,
        dedup_tokens_saved=dedup_saved,
        integrity_skipped=unmatched_tool_calls,
        archive_written_count=sum(1 for item in offload_results if not item.reused),
        archive_reused_count=sum(1 for item in offload_results if item.reused),
        archive_bytes_written=sum(item.stored_bytes for item in offload_results if not item.reused),
        archive_bytes_reused=sum(item.stored_bytes for item in offload_results if item.reused),
    )

    return messages, final_saved


def _record_compression_to_metrics(
    tokens_saved: int,
    compression_type: str,
    details: str = "",
    *,
    group_count: int = 0,
    dedup_tokens_saved: int = 0,
    integrity_skipped: int = 0,
    archive_written_count: int = 0,
    archive_reused_count: int = 0,
    archive_bytes_written: int = 0,
    archive_bytes_reused: int = 0,
) -> None:
    """记录压缩事件到 TaskMetrics

    Args:
        tokens_saved: 节省的 token 数
        compression_type: 压缩类型
        details: 详细信息
    """
    try:
        from myrm_agent_harness.agent.context_management.infra.session_lock import get_current_chat_id
        from myrm_agent_harness.agent.context_management.tracking.task_metrics import get_task_metrics

        chat_id = get_current_chat_id()
        if chat_id:
            metrics = get_task_metrics(chat_id)
            if metrics:
                # 类型转换
                valid_types = ("filter", "cache_ttl_prune", "compress", "summarize")
                ct = compression_type if compression_type in valid_types else "compress"
                metrics.record_compression(
                    tokens_saved=tokens_saved,
                    compression_type=ct,  # type: ignore
                    details=details,
                    group_count=group_count,
                    dedup_tokens_saved=dedup_tokens_saved,
                    integrity_skipped=integrity_skipped,
                    archive_written_count=archive_written_count,
                    archive_reused_count=archive_reused_count,
                    archive_bytes_written=archive_bytes_written,
                    archive_bytes_reused=archive_bytes_reused,
                )
    except Exception as e:
        logger.warning(f"[压缩] 记录到 TaskMetrics 失败: {e}")


async def compress_tool_message_async(
    tool_msg: ToolMessage,
    ai_msg: AIMessage | None = None,
    *,
    on_offload: ContextCompressOffloadCallback | None = None,
    chat_id: str | None = None,
    user_id: str | None = None,
    offload_results: list[ContextOffloadResult] | None = None,
) -> int:
    """将单个工具消息转换为压缩格式

    Args:
        tool_msg: 工具消息
        ai_msg: 对应的 AI 消息(包含工具调用参数)
        on_offload: 压缩前将完整原文落盘的回调(可选)
        chat_id: 会话 ID(传入回调)
        user_id: 用户 ID(仅用于兼容上层调用; 不会传入归档回调)

    Returns:
        节省的 token 数
    """
    tool_name = tool_msg.name or "unknown"

    if _is_already_compressed(tool_msg):
        return 0

    # Strip base64 images from multimodal content before compression.
    # Without this, json.dumps(base64) would treat huge image data as text tokens.
    if isinstance(tool_msg.content, list):
        from myrm_agent_harness.utils.image_utils import content_has_images, strip_images_from_content

        content_items = cast(list[object], tool_msg.content)
        if content_has_images(content_items):
            stripped = strip_images_from_content(content_items)
            if isinstance(stripped, list):
                text_parts: list[str] = []
                all_text = True
                for part in stripped:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(str(part.get("text", "")))
                    else:
                        all_text = False
                        break
                if all_text:
                    tool_msg.content = "\n".join(text_parts)

    original_content = tool_msg.content if isinstance(tool_msg.content, str) else json.dumps(tool_msg.content)
    original_tokens = get_token_count(original_content)

    rule = COMPACT_RULES.get(tool_name)
    identifier = extract_identifier(tool_msg, ai_msg, rule.identifier_arg if rule else "id")
    identifier_type = rule.identifier_type if rule else "other"

    # 提取工具参数(用于统计信息提取)
    tool_args: dict[str, object] | None = None
    if ai_msg and ai_msg.tool_calls:
        for tc in ai_msg.tool_calls:
            if tc.get("id") == tool_msg.tool_call_id:
                tool_args = tc.get("args", {})
                break

    # 【新增】提取统计信息
    tool_stats = extract_tool_stats(tool_name, original_content, tool_args)

    evicted_path: str | None = None
    if on_offload is not None and original_tokens >= OFFLOAD_THRESHOLD_TOKENS:
        try:
            offload_result = normalize_context_offload_result(
                await on_offload(content=original_content, tool_name=tool_name, scope_id=chat_id)
            )
            if offload_result.succeeded:
                if offload_results is not None:
                    offload_results.append(offload_result)
                evicted_path = offload_result.path
                logger.info("[压缩] 已落盘 %s (%d tokens) → %s", tool_name, original_tokens, evicted_path)
            elif offload_result.message:
                logger.warning(
                    "[压缩] compress offload denied for %s kind=%s: %s",
                    tool_name,
                    offload_result.failure_kind,
                    offload_result.message,
                )
        except Exception as exc:
            logger.warning("[压缩] compress offload failed for %s: %s", tool_name, exc)

    compact_info = CompactToolCall(
        tool_name=tool_name,
        identifier=identifier,
        identifier_type=identifier_type,
        timestamp=datetime.now().isoformat(),
        original_tokens=original_tokens,
        evicted_path=evicted_path,
    )

    # Use stats-aware templates only when the source content is large enough to benefit.
    if rule:
        stats_template = rule.stats_template
        if stats_template is not None and tool_stats and original_tokens >= 25:
            compressed_content = generate_compressed_content_with_stats(compact_info, stats_template, tool_stats)
        else:
            compressed_content = generate_compressed_content(compact_info, rule.result_template)
    else:
        compressed_content = generate_generic_compressed_content(compact_info, tool_stats)

    tool_msg.content = compressed_content

    # Shrink corresponding AIMessage tool_call args to prevent
    # oversized JSON arguments from causing API 400 after compression
    if ai_msg and ai_msg.tool_calls:
        shrunk_tool_calls = shrink_tool_call_args(cast(list[dict[str, object]], ai_msg.tool_calls))
        ai_msg.tool_calls = cast(list[ToolCall], shrunk_tool_calls)

    # Record file reference and access if offloaded
    if evicted_path and chat_id:
        tracking_task = asyncio.create_task(_record_file_tracking_async(evicted_path, tool_msg, chat_id))
        _file_tracking_tasks.add(tracking_task)
        tracking_task.add_done_callback(_file_tracking_tasks.discard)

    new_tokens = get_token_count(compressed_content)
    saved_tokens = original_tokens - new_tokens

    log_suffix = f", offload={evicted_path}" if evicted_path else ""
    logger.warning(f" [压缩] {tool_name}: {original_tokens} → {new_tokens} tokens{log_suffix}")

    return saved_tokens


def _is_already_compressed(tool_msg: ToolMessage) -> bool:
    """检查 ToolMessage 是否已经被压缩过

    Args:
        tool_msg: 工具消息

    Returns:
        是否已压缩
    """
    content = tool_msg.content if isinstance(tool_msg.content, str) else ""
    # Line-based 格式以 "COMPACTED:" 开头
    return content.startswith("COMPACTED:")


async def _record_file_tracking_async(evicted_path: str, tool_msg: ToolMessage, chat_id: str) -> None:
    """Record file tracking information asynchronously (non-blocking).

    Args:
        evicted_path: Relative path to offloaded file
        tool_msg: Tool message containing reference
        chat_id: Session identifier
    """
    try:
        from myrm_agent_harness.runtime.context.file_access_tracker import get_file_access_tracker
        from myrm_agent_harness.runtime.context.instance_metrics import record_file_access
        from myrm_agent_harness.runtime.execution_paths import PERSISTENT_ROOT

        file_path = f"{PERSISTENT_ROOT}/{evicted_path}"

        access_tracker = await get_file_access_tracker()
        await access_tracker.record_access(file_path, session_id=chat_id)
        record_file_access()
    except Exception as exc:
        logger.debug(f"Failed to record file tracking for {evicted_path}: {exc}")
