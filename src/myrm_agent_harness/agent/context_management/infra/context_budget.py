"""上下文预算监控模块

提供实时的上下文使用情况监控和可视化。

功能：
1. 计算当前上下文的 token 使用量
2. 显示各阈值的使用百分比
3. 提供结构化的 ContextBudget 数据
4. 生成可视化的进度条

阈值说明（从低到高，基于 max_context_tokens 动态计算）：
- compress_threshold (50% of max_context): 压缩触发阈值（开始压缩旧工具结果）
- summarize_threshold (90% of max_context): 摘要触发阈值（压缩不够时生成结构化摘要）

注意：summarize_threshold 是实际的上限，摘要失败会抛出异常并终止任务。

1. agent/context_management/PROMPT_CACHE_PRACTICE.md §4.3 动态阈值

上下文管理三层防线：
1. 第一层 - 模型主动外部化：模型在任务进行中主动将关键发现写入文件（如 notes.md）
   这不是系统行为，而是通过 prompt 引导 Agent 自主决定。
   作用：确保关键信息永久保存，不受任何上下文压缩/摘要影响。
2. 第二层 - 压缩（可逆）：达到 compress_threshold 时，系统将旧工具调用结果
   外部化到 .context/ 目录，上下文只保留引用，模型可通过 cat 恢复。
3. 第三层 - 摘要（不可逆）：达到 summarize_threshold 时，系统生成结构化摘要，
   其中 files_modified 字段会告诉模型之前写入了哪些文件，便于按需恢复。

[INPUT]
- (none)

[OUTPUT]
- ContextHealthStatus: class — Context Health Status
- ContextBudget: Attributes:
- calculate_context_budget: Args:
- format_budget_log: Args:

[POS]
Provides ContextHealthStatus, ContextBudget, calculate_context_budget.
"""

from dataclasses import dataclass
from enum import StrEnum

from langchain_core.messages import BaseMessage

from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from .schemas import ContextConfig


class ContextHealthStatus(StrEnum):
    """上下文健康状态"""

    HEALTHY = "healthy"  # 低于压缩阈值
    WARNING = "warning"  # 接近压缩阈值（>80%）
    CRITICAL = "critical"  # 接近摘要阈值（>80%），摘要失败会终止任务


@dataclass
class ContextBudget:
    """上下文预算数据

    Attributes:
        current_tokens: 当前使用的 token 数
        compress_threshold: 压缩触发阈值
        summarize_threshold: 摘要触发阈值（实际上限，失败会终止任务）
        config: 使用的配置实例
    """

    current_tokens: int
    compress_threshold: int
    summarize_threshold: int
    config: ContextConfig

    @property
    def compress_usage(self) -> float:
        """压缩阈值使用率 (0.0 - 1.0+)"""
        return self.current_tokens / self.compress_threshold if self.compress_threshold > 0 else 0.0

    @property
    def summarize_usage(self) -> float:
        """摘要阈值使用率 (0.0 - 1.0+)

        这是实际的上限使用率，摘要失败会终止任务。
        """
        if self.summarize_threshold is None or self.summarize_threshold <= 0:
            return 0.0
        if self.current_tokens is None:
            return 0.0
        return self.current_tokens / self.summarize_threshold

    @property
    def health_status(self) -> ContextHealthStatus:
        """上下文健康状态"""
        if self.summarize_usage >= 0.8:
            return ContextHealthStatus.CRITICAL
        if self.compress_usage >= 0.8:
            return ContextHealthStatus.WARNING
        return ContextHealthStatus.HEALTHY

    @property
    def remaining_until_compress(self) -> int:
        """距离压缩阈值还剩多少 token"""
        return max(0, self.compress_threshold - self.current_tokens)

    @property
    def remaining_until_summarize(self) -> int:
        """距离摘要阈值还剩多少 token"""
        return max(0, self.summarize_threshold - self.current_tokens)

    @property
    def remaining_ratio(self) -> float:
        """剩余空间占总容量的比例 (0.0 - 1.0)

        基于 summarize_threshold（实际上限）计算。
        """
        try:
            usage = self.summarize_usage
            if usage is None:
                return 1.0  # 如果无法计算使用率，假设有 100% 剩余
            return max(0.0, 1.0 - usage)
        except Exception:
            return 1.0  # 发生异常时返回默认值

    def get_dynamic_compress_min_save(self) -> int:
        """根据剩余空间动态计算 compress_min_save

        策略：
        - 剩余 > 50%：使用配置的默认值（保守策略，保护 Prompt Cache）
        - 剩余 20-50%：降低阈值到 60%（适度激进）
        - 剩余 10-20%：降低阈值到 40%（激进清理）
        - 剩余 < 10%：降低阈值到 20%（紧急模式，尽可能延长对话）

        Returns:
            动态计算后的 compress_min_save 值
        """
        # 安全获取配置值，防止 None
        base_min_save = self.config.compress_min_save if self.config.compress_min_save is not None else 3000
        remaining = self.remaining_ratio if self.remaining_ratio is not None else 1.0

        if remaining > 0.5:
            # 还有超过50%空间，使用默认阈值
            return base_min_save
        elif remaining > 0.2:
            # 剩余 20-50%，降低到 60%
            return int(base_min_save * 0.6)
        elif remaining > 0.1:
            # 剩余 10-20%，降低到 40%
            return int(base_min_save * 0.4)
        else:
            # 剩余不到 10%，紧急模式，降低到 20%
            # 最低不少于 500 tokens（避免过于激进）
            return max(500, int(base_min_save * 0.2))

    def calculate_dynamic_thresholds(self, turn_count: int, estimated_remaining_turns: int = 10) -> tuple[int, int]:
        """根据会话进度动态计算压缩触发阈值

        核心思想：
        - 短对话（轮数少）：阈值较高，不着急压缩
        - 长对话（轮数多）：阈值降低，提前准备空间
        - 接近上限时：阈值最低，积极压缩

        Args:
            turn_count: 当前会话轮数（human 消息数）
            estimated_remaining_turns: 预估剩余轮数

        Returns:
            (dynamic_compress_threshold, dynamic_min_save)
        """
        # 安全获取配置值，防止 None
        base_threshold = self.compress_threshold if self.compress_threshold is not None else 60000
        base_min_save = self.config.compress_min_save if self.config.compress_min_save is not None else 3000

        # 早期保护：轮数太少时估算不准确，使用默认阈值
        if turn_count < 5:
            return base_threshold, base_min_save

        # 1. 计算每轮平均消耗
        avg_tokens_per_turn = (self.current_tokens if self.current_tokens is not None else 0) / turn_count

        # 2. 预估剩余需要的空间
        estimated_remaining_tokens = avg_tokens_per_turn * estimated_remaining_turns

        # 3. 计算剩余空间（基于 summarize_threshold，实际上限）
        remaining_tokens = self.summarize_threshold - self.current_tokens

        # 4. 计算"紧张度" = 剩余空间 / 预估需要
        #    urgency > 2.0: 很宽松
        #    urgency 1.0-2.0: 中等
        #    urgency 0.5-1.0: 紧张
        #    urgency < 0.5: 非常紧张
        if estimated_remaining_tokens > 0:
            urgency = remaining_tokens / estimated_remaining_tokens
        else:
            urgency = 2.0  # 默认宽松

        # 5. 根据紧张度动态调整阈值
        if urgency > 2.0:
            # 很宽松：使用默认阈值
            threshold = base_threshold
            min_save = base_min_save
        elif urgency > 1.0:
            # 中等：略微降低阈值到 80%
            threshold = int(base_threshold * 0.80)
            min_save = int(base_min_save * 0.80)
        elif urgency > 0.5:
            # 紧张：降低到 60%
            threshold = int(base_threshold * 0.60)
            min_save = int(base_min_save * 0.60)
        else:
            # 非常紧张：降低到 50%
            threshold = int(base_threshold * 0.50)
            min_save = max(500, int(base_min_save * 0.40))

        return threshold, min_save

    def to_dict(self) -> dict[str, int | float | str]:
        """转换为字典，便于 API 返回"""
        return {
            "current_tokens": self.current_tokens,
            "compress_threshold": self.compress_threshold,
            "summarize_threshold": self.summarize_threshold,
            "compress_usage_percent": round(self.compress_usage * 100, 1),
            "summarize_usage_percent": round(self.summarize_usage * 100, 1),
            "health_status": self.health_status.value,
            "remaining_until_compress": self.remaining_until_compress,
            "remaining_ratio": round(self.remaining_ratio, 3),
            "dynamic_compress_min_save": self.get_dynamic_compress_min_save(),
        }

    def to_progress_bar(self, width: int = 40) -> str:
        """生成可视化进度条

        Args:
            width: 进度条宽度（字符数）

        Returns:
            带进度条的字符串
        """
        usage = min(self.summarize_usage, 1.0)
        filled = int(width * usage)
        empty = width - filled

        # 根据使用率选择颜色标记
        status_emoji = {
            ContextHealthStatus.CRITICAL: "",
            ContextHealthStatus.WARNING: "",
            ContextHealthStatus.HEALTHY: "",
        }
        bar_char = status_emoji.get(self.health_status, "")

        bar = "█" * filled + "░" * empty
        return f"{bar_char} [{bar}] {self.current_tokens:,}/{self.summarize_threshold:,} tokens ({self.summarize_usage * 100:.1f}%)"

    def to_detailed_view(self) -> str:
        """生成详细的可视化视图

        Returns:
            多行的详细视图字符串
        """
        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║                     CONTEXT BUDGET                         ║",
            "╠══════════════════════════════════════════════════════════════╣",
            f"║  Current: {self.current_tokens:>8,} tokens                              ║",
            "║                                                              ║",
        ]

        # 添加各阈值的使用情况
        thresholds = [
            ("Compress", self.compress_threshold, self.compress_usage),
            ("Summarize", self.summarize_threshold, self.summarize_usage, " (上限)"),
        ]

        for item in thresholds:
            name, threshold, usage = item[:3]
            suffix = item[3] if len(item) > 3 else ""
            status = ""
            bar_width = 20
            filled = min(int(bar_width * usage), bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            lines.append(f"║  {status} {name:<12} {threshold:>7,} [{bar}] {usage * 100:>5.1f}%{suffix}  ║")

        lines.extend(
            [
                "║                                                              ║",
                f"║  Health Status: {self.health_status.value.upper():<40}     ║",
                f"║  Remaining (compress): {self.remaining_until_compress:>8,} tokens             ║",
                "╚══════════════════════════════════════════════════════════════╝",
            ]
        )

        return "\n".join(lines)


def calculate_context_budget(messages: list[BaseMessage], config: ContextConfig | None = None) -> ContextBudget:
    """计算当前上下文预算

    Args:
        messages: 消息列表
        config: 上下文配置（可选，默认使用 128k 窗口）

    Returns:
        ContextBudget 对象
    """
    from .schemas import DEFAULT_CONTEXT_CONFIG

    cfg = config or DEFAULT_CONTEXT_CONFIG

    total_tokens = estimate_messages_tokens(messages)

    return ContextBudget(
        current_tokens=total_tokens,
        compress_threshold=cfg.compress_threshold,
        summarize_threshold=cfg.summarize_trigger_threshold,
        config=cfg,
    )


def format_budget_log(budget: ContextBudget) -> str:
    """格式化预算日志（单行）

    Args:
        budget: ContextBudget 对象

    Returns:
        格式化的日志字符串
    """
    status_emoji = {
        ContextHealthStatus.HEALTHY: "",
        ContextHealthStatus.WARNING: "",
        ContextHealthStatus.CRITICAL: "",
    }

    emoji = status_emoji.get(budget.health_status, "")

    return (
        f"{emoji} Context Budget: "
        f"{budget.current_tokens:,}/{budget.summarize_threshold:,} tokens "
        f"({budget.summarize_usage * 100:.1f}%) | "
        f"Compress: {budget.compress_usage * 100:.0f}% | "
        f"Summarize: {budget.summarize_usage * 100:.0f}%"
    )
