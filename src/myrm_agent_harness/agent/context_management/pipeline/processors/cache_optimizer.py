"""Explicit cache processor.

Adds provider cache-control markers for Anthropic and Qwen-compatible models.
The processor runs after context reduction so breakpoints match the final
message list. It uses endpoint-aware TTL selection: direct Anthropic, Vertex,
and LiteLLM anthropic routing use 1h; proxy or unknown endpoints use the
default ephemeral cache policy.

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain message base class)
- infra.cache_metrics_collector::PendingExplicitCacheSnapshot (POS: Request-scoped explicit cache metrics snapshot)
- utils.token_estimation::estimate_messages_tokens (POS: Message token estimation)
- pipeline.base::BaseProcessor, ProcessorContext (POS: Context pipeline processor contract)

[OUTPUT]
- ExplicitCacheProcessor: injects provider cache-control markers and records expected cacheable-token snapshots.

[POS]
Provider explicit-cache marker processor. Computes stable cache breakpoints for
providers that require explicit cache-control metadata.
"""

from langchain_core.messages import BaseMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from ...infra.cache_metrics_collector import PendingExplicitCacheSnapshot, set_pending_explicit_cache_snapshot
from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)


# Anthropic 官方限制：断点间最小 token 数
# 参考：https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
ANTHROPIC_MIN_CACHEABLE_TOKENS = 1024  # Claude Sonnet/Opus 4 系列的最小要求


class ExplicitCacheProcessor(BaseProcessor):
    """显式缓存处理器（官方最佳实践）

     适用范围：只处理需要显式 cache_control 标记的模型
    -  Anthropic Claude 系列
    -  阿里云 Qwen/DashScope 系列
    -  OpenAI/DeepSeek/Gemini（使用自动前缀缓存，无需显式标记）

    基于 Anthropic 官方文档的 Prompt Caching 最佳实践：
    https://platform.claude.com/docs/en/build-with-claude/prompt-caching

    断点策略：
    1. System 后（必须）              - 缓存系统提示词
    2. 每 ~15 blocks（自动）          - 防止超出 20-block lookback window
    3. 压缩边界后（按需）             - 保护压缩内容
    4. 最后一条消息（必须）           - 增量对话缓存（官方推荐）

    成本优化：
    - 命中缓存：只需支付 5% 的 input tokens
    - 新增内容：支付 125% 的 input tokens（创建缓存）
    - Anthropic 官方数据：68% 成本节省（9 轮对话，增量缓存 vs 无缓存）

    关键特性：
    -  零配置：完全自动化，无需手动调整
    -  增量缓存：每轮只缓存新增内容，不重复缓存旧内容
    -  20-block 保护：自动处理 Anthropic 的 lookback window 限制
    -  压缩感知：与压缩处理器深度协同
    """

    def __init__(
        self,
        safe_block_interval: int = 15,  # 每 15 blocks 设置一个保护性断点
        min_message_gap: int = 6,  # 断点间最小消息数（fallback 策略）
        max_breakpoints: int = 4,  # Anthropic/阿里云限制
    ):
        """初始化缓存优化器

        Args:
            safe_block_interval: 保护性断点间隔（blocks），默认 15
                - Anthropic 限制是 20 blocks lookback window
                - 设置 15 预留 5 blocks 安全余量
                - 有效范围：1-19
            min_message_gap: 断点间最小消息间隔，默认 6 条消息
                - 主验证：使用实际 token 计算（≥ 1024 tokens）
                - Fallback：当 tokens 不足但消息数满足时，仍保留断点
                - 场景：短消息密集对话，依然需要保护断点防止超出 lookback window
                - 有效范围：1-10
            max_breakpoints: 最大断点数，默认 4（Anthropic/阿里云限制）
                - 有效范围：1-4

        Raises:
            ValueError: 参数超出有效范围
        """
        # 参数验证
        if not isinstance(safe_block_interval, int) or not 1 <= safe_block_interval <= 19:
            raise ValueError(
                f"safe_block_interval 必须是 1-19 之间的整数（基于 20-block lookback window 限制），"
                f"当前值: {safe_block_interval}"
            )

        if not isinstance(min_message_gap, int) or not 1 <= min_message_gap <= 10:
            raise ValueError(f"min_message_gap 必须是 1-10 之间的整数，当前值: {min_message_gap}")

        if not isinstance(max_breakpoints, int) or not 1 <= max_breakpoints <= 4:
            raise ValueError(
                f"max_breakpoints 必须是 1-4 之间的整数（Anthropic/阿里云限制），当前值: {max_breakpoints}"
            )

        self.safe_block_interval = safe_block_interval
        self.min_message_gap = min_message_gap
        self.max_breakpoints = max_breakpoints

    @property
    def name(self) -> str:
        return "explicit_cache"

    async def should_process(self, context: ProcessorContext) -> bool:
        """检测是否需要显式缓存处理

        只处理需要显式 cache_control 标记的模型：
        - Anthropic Claude
        - 阿里云 Qwen/DashScope
        """
        # 检测模型是否需要显式 cache_control
        model_name_raw = context.metadata.get("model_name", "")
        model_name = model_name_raw if isinstance(model_name_raw, str) else ""
        return self._needs_explicit_caching(model_name)

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        """执行缓存优化（官方最佳实践）

        Resume 模式：只在最后一条消息设置断点（增量缓存）
        Normal 模式：设置所有断点（System后 + 每15 blocks + 压缩边界 + 最后一条）
        """
        # 1. 计算断点位置
        breakpoints = self._calculate_breakpoints(context)

        if not breakpoints:
            logger.warning(" [ExplicitCache] 无需设置断点")
            return context

        # 2. 在消息中注入 cache_control
        context.messages = self._inject_cache_control(context.messages, breakpoints, context)

        # 3. 记录统计信息并输出日志
        total_tokens = estimate_messages_tokens(context.messages)
        msg_count = len(context.messages)
        turn_count_raw = context.metadata.get("turn_count", 0)
        turn_count = turn_count_raw if isinstance(turn_count_raw, int) else 0

        # 计算预期可缓存的 tokens
        expected_cacheable_tokens = self._calculate_expected_cacheable_tokens(context.messages, breakpoints)

        # 计算预期命中率（仅用于日志显示）
        expected_hit_rate_pct = 0
        if turn_count > 1 and total_tokens > 0:
            expected_hit_rate_pct = int((expected_cacheable_tokens / total_tokens) * 100)

        logger.warning(
            f" [ExplicitCache] "
            f"Breakpoints: {len(breakpoints)} at {breakpoints} | "
            f"Messages: {msg_count} | Turns: {turn_count} | "
            f"Total: ~{total_tokens} tokens | "
            f"Expected Cache: {expected_hit_rate_pct}%"
        )

        compression_raw = context.metadata.get("compression_count", 0)
        compression_count = int(compression_raw) if isinstance(compression_raw, int) else 0

        set_pending_explicit_cache_snapshot(
            PendingExplicitCacheSnapshot(
                turn_count=turn_count,
                breakpoint_count=len(breakpoints),
                message_count=msg_count,
                total_estimated_tokens=total_tokens,
                expected_cacheable_tokens=expected_cacheable_tokens,
                compression_count=compression_count,
            )
        )

        return context

    def _needs_explicit_caching(self, model_name: str) -> bool:
        """判断模型是否需要显式缓存控制

        Anthropic 和阿里云需要显式 cache_control 标记。
        OpenAI/DeepSeek 使用自动前缀缓存，不需要显式标记。
        """
        if not model_name:
            return False

        model_lower = model_name.lower()
        prefixes = ("anthropic/", "claude-", "qwen", "dashscope/", "openai/qwen")
        return any(model_lower.startswith(p) for p in prefixes)

    def _calculate_breakpoints(self, context: ProcessorContext) -> list[int]:
        """计算缓存断点位置（官方最佳实践）

        官方推荐策略：
        1. System 后（必须）              - 缓存系统提示词
        2. 每 ~15 blocks（自动）          - 防止超出 20-block lookback window
        3. 压缩边界后（按需）             - 保护压缩内容
        4. 最后一条消息（必须）           - 增量对话缓存

        Resume 模式：只在最后一条消息设置断点（增量缓存）
        Anthropic 会自动向前查找匹配的缓存前缀，无需重复标记历史断点。

        官方文档原文：
        > "During each turn, we mark the final block of the final message with
        > cache_control so the conversation can be incrementally cached."

        Returns:
            消息索引列表（从 0 开始）
        """
        messages = context.messages

        # 边界检查：空消息列表
        if not messages:
            logger.warning(" [ExplicitCache] 消息列表为空，跳过断点计算")
            return []

        # Resume 模式：仅最后一条消息（增量缓存）
        if context.is_resume:
            last_idx = len(messages) - 1
            logger.info(f" [ExplicitCache] Resume mode: only last message #{last_idx} ({messages[last_idx].type})")
            return [last_idx]

        # 边界检查：单条消息
        if len(messages) == 1:
            logger.info(f" [ExplicitCache] 单条消息，直接设置断点: #0 ({messages[0].type})")
            return [0]

        breakpoints = []

        try:
            # 1 System 消息后（必须）
            system_idx = self._find_system_message_index(messages)
            if system_idx >= 0:
                breakpoints.append(system_idx)
                last_bp = system_idx
            else:
                last_bp = -1

            # 2 20-block 保护断点（按 content blocks 计数）
            # Anthropic 的 lookback window 按 content blocks 计数，不是消息数。
            # 一条 AIMessage 带 3 个 tool_use 就是 4 blocks，所以必须按 blocks 累积。
            blocks_since_last_bp = 0
            for i in range(last_bp + 1, len(messages) - 1):
                blocks_since_last_bp += self._estimate_content_blocks(messages[i])
                if blocks_since_last_bp >= self.safe_block_interval:
                    optimal_idx = self._find_nearest_assistant(messages, i, last_bp)
                    if optimal_idx >= 0 and optimal_idx not in breakpoints:
                        breakpoints.append(optimal_idx)
                        last_bp = optimal_idx
                        blocks_since_last_bp = 0

            # 3 压缩边界后（如果有且距离合适）
            compress_idx_raw = context.metadata.get("last_compress_boundary_index")
            compress_idx = compress_idx_raw if isinstance(compress_idx_raw, int) else None
            if (
                compress_idx is not None
                and compress_idx not in breakpoints
                and compress_idx < len(messages) - 1
            ):
                # 检查距离：至少间隔 min_message_gap 条消息
                prev_bps = [b for b in breakpoints if b < compress_idx]
                if not prev_bps or (compress_idx - max(prev_bps)) >= self.min_message_gap:
                    breakpoints.append(compress_idx)

            # 4 最后一条消息（必须！官方推荐）
            # 官方文档：在每轮的最后一条消息设置 cache_control
            # 系统会自动向前查找之前的缓存，实现增量缓存
            last_idx = len(messages) - 1
            if last_idx >= 0 and last_idx not in breakpoints:
                breakpoints.append(last_idx)

            # 验证并排序
            from .cache_breakpoint_validator import validate_breakpoints

            breakpoints = validate_breakpoints(breakpoints, messages, self.min_message_gap, self.max_breakpoints)

            logger.info(
                f" [ExplicitCache] 断点策略 | "
                f"System: #{system_idx if system_idx >= 0 else 'N/A'} | "
                f"20-block保护: {len([b for b in breakpoints if b not in [system_idx, compress_idx, last_idx]])} 个 | "
                f"压缩边界: #{compress_idx if compress_idx else 'N/A'} | "
                f"最后消息: #{last_idx}"
            )

            return sorted(breakpoints)

        except Exception as e:
            # 错误处理：降级策略
            logger.error(
                f" [ExplicitCache] 断点计算失败: {type(e).__name__}: {e}，使用降级策略（仅缓存最后一条消息）"
            )
            # 降级：至少缓存最后一条消息（官方推荐的核心）
            last_idx = len(messages) - 1
            return [last_idx] if last_idx >= 0 else []

    def _find_system_message_index(self, messages: list[BaseMessage]) -> int:
        """查找第一个 System 消息索引（Sandbox 场景下最大化跨用户缓存）"""
        for i, msg in enumerate(messages):
            if msg.type == "system":
                return i
        return -1

    @staticmethod
    def _estimate_content_blocks(msg: BaseMessage) -> int:
        """估算一条消息在 Anthropic API 中产生的 content blocks 数。

        Anthropic 的 20-block lookback window 按 content blocks 计数：
        - HumanMessage / ToolMessage / SystemMessage → 1 block
        - AIMessage（纯文本）→ 1 block
        - AIMessage（带 N 个 tool_use）→ 1 text block + N tool_use blocks
        """
        if msg.type == "ai":
            tool_calls: list[object] = getattr(msg, "tool_calls", None) or []
            return 1 + len(tool_calls)
        return 1

    def _find_nearest_assistant(self, messages: list[BaseMessage], target_pos: int, min_pos: int = -1) -> int:
        """找到目标位置附近最近的 Assistant 消息

        优先向后查找（距离 ≤ 3），否则向前查找。
        在 Assistant 消息后设置断点，实现增量缓存。

        Args:
            messages: 消息列表
            target_pos: 目标位置
            min_pos: 最小位置（不能小于这个位置）

        Returns:
            最近的 Assistant 消息索引，未找到返回 -1
        """
        # 向后查找（优先，距离 ≤ 3）
        for i in range(target_pos, min(target_pos + 4, len(messages))):
            if i > min_pos and messages[i].type == "ai":
                return i

        # 向前查找
        for i in range(target_pos - 1, min_pos, -1):
            if messages[i].type == "ai":
                return i

        return -1

    def _calculate_expected_cacheable_tokens(self, messages: list[BaseMessage], breakpoints: list[int]) -> int:
        """计算预期可缓存的 tokens 数

        根据断点位置，计算从开始到最后一个断点的 tokens 总数。
        这些 tokens 在后续轮次中有望被缓存命中。

        Args:
            messages: 消息列表
            breakpoints: 断点索引列表（已排序）

        Returns:
            预期可缓存的 tokens 数
        """
        if not breakpoints or not messages:
            return 0

        # 计算从开始到最后一个断点的所有消息的 tokens
        last_breakpoint = breakpoints[-1]
        cacheable_messages = messages[: last_breakpoint + 1]

        return estimate_messages_tokens(cacheable_messages)

    def _resolve_cache_control_value(self, context: ProcessorContext) -> dict[str, str]:
        """Resolve the cache_control value based on endpoint eligibility.

        Anthropic supports extended 1h TTL on direct API and Google Vertex endpoints.
        Default 5min TTL (ephemeral without explicit ttl) is used for proxies and
        unrecognized endpoints where 1h may not be supported.

        Resolution priority:
        1. metadata["cache_retention"] = "long" → force 1h
        2. metadata["cache_retention"] = "none" → default 5min
        3. base_url contains api.anthropic.com or aiplatform.googleapis.com → 1h
        4. base_url empty + model_name starts with "anthropic/" → 1h (LiteLLM direct routing)
        5. Otherwise → default 5min (conservative)

        Reference: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
        """
        cache_retention = context.metadata.get("cache_retention", "")

        if cache_retention == "long":
            return {"type": "ephemeral", "ttl": "1h"}

        if cache_retention == "none":
            return {"type": "ephemeral"}

        base_url = str(context.metadata.get("base_url", ""))
        if self._is_long_ttl_eligible_endpoint(base_url):
            return {"type": "ephemeral", "ttl": "1h"}

        # LiteLLM routing: "anthropic/" prefix always routes to Anthropic direct API
        if not base_url:
            model_name = str(context.metadata.get("model_name", "")).lower()
            if model_name.startswith("anthropic/"):
                return {"type": "ephemeral", "ttl": "1h"}

        return {"type": "ephemeral"}

    @staticmethod
    def _is_long_ttl_eligible_endpoint(base_url: str) -> bool:
        """Check if the endpoint supports extended 1h cache TTL.

        Only Anthropic direct API and Google Vertex AI endpoints are confirmed
        to support the 1h TTL extension. Proxies (OpenRouter, AWS Bedrock via
        proxy, etc.) may not forward the ttl field correctly.
        """
        if not base_url:
            return False

        lower = base_url.lower()
        return (
            "api.anthropic.com" in lower
            or "aiplatform.googleapis.com" in lower
        )

    def _inject_cache_control(self, messages: list[BaseMessage], breakpoints: list[int],
                              context: ProcessorContext) -> list[BaseMessage]:
        """在指定消息位置注入 cache_control 标记

        Args:
            messages: 消息列表
            breakpoints: 断点索引列表
            context: 处理器上下文（用于解析 TTL 策略）

        Returns:
            注入后的消息列表（会创建副本）
        """
        if not breakpoints:
            return messages

        cache_control = self._resolve_cache_control_value(context)

        # 创建消息副本（避免修改原始消息）
        messages = [msg.model_copy(deep=True) for msg in messages]

        for idx in breakpoints:
            if 0 <= idx < len(messages):
                msg = messages[idx]

                if not hasattr(msg, "additional_kwargs"):
                    msg.additional_kwargs = {}

                msg.additional_kwargs["cache_control"] = cache_control

                logger.debug(f" 在消息 #{idx} ({msg.type}) 注入 cache_control")

        return messages
