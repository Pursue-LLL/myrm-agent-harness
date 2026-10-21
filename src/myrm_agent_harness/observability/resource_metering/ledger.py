"""
[INPUT]
- .models::CognitiveUsage, HardwareUsage, HybridLedgerReport (POS: 混合算力模型)

[OUTPUT]
- ResourceMeteringLedger: 物理硬件占用与认知算力统一对账引擎
- BudgetCircuitBreaker: 任务多维资源与预算防超支熔断器

[POS]
myrm-agent-harness/src/myrm_agent_harness/observability/resource_metering/ledger.py — 双轨算力计量对账与预算熔断引擎。
"""

from __future__ import annotations

from .models import CognitiveUsage, HardwareUsage, HybridLedgerReport


class BudgetCircuitBreaker:
    """任务多维硬件与认知预算防超支熔断器。"""

    def __init__(
        self,
        max_execution_seconds: float | None = None,
        max_total_tokens: int | None = None,
        max_total_credits: float | None = None,
    ) -> None:
        self.max_execution_seconds = max_execution_seconds
        self.max_total_tokens = max_total_tokens
        self.max_total_credits = max_total_credits

    def check(
        self,
        hardware: HardwareUsage,
        cognitive: CognitiveUsage,
        total_credits: float,
    ) -> tuple[bool, str]:
        """检查当前消耗是否已触及熔断红线。"""
        if self.max_execution_seconds is not None and hardware.execution_seconds > self.max_execution_seconds:
            return (
                True,
                f"物理沙箱运行时间 ({hardware.execution_seconds:.1f}s) 超出最大预算配额 ({self.max_execution_seconds:.1f}s)",
            )

        total_tokens = cognitive.prompt_tokens + cognitive.completion_tokens
        if self.max_total_tokens is not None and total_tokens > self.max_total_tokens:
            return (
                True,
                f"认知 Token 消耗总数 ({total_tokens:,}) 超出最大预算配额 ({self.max_total_tokens:,})",
            )

        if self.max_total_credits is not None and total_credits > self.max_total_credits:
            return (
                True,
                f"综合算力积分总消耗 ({total_credits:.2f}) 超出最大预算配额 ({self.max_total_credits:.2f} Credits)",
            )

        return (False, "")


class ResourceMeteringLedger:
    """物理机器时长与认知 Token 统一折算与全景对账引擎（对标火山方舟 AFP 协议）。"""

    # 硬件计量费率：基准沙箱 (2C/4G) 每秒消耗 0.017361 AFP (约每小时 62.5 AFP)
    BASE_HARDWARE_CREDITS_PER_SEC: float = 0.017361
    # 磁盘 Volume 读写：每 MB 读写消耗 0.0001 AFP
    VOLUME_IO_CREDITS_PER_MB: float = 0.0001

    # 认知 Token 计量费率 (按每 1000 Tokens 计算标准积分)
    PROMPT_CREDITS_PER_1K: float = 0.50
    COMPLETION_CREDITS_PER_1K: float = 1.50
    CACHED_PROMPT_CREDITS_PER_1K: float = 0.10

    # 积分与法币折算：100 Credits = $1.00 USD
    CREDITS_TO_USD_RATE: float = 0.01

    def calculate_hardware_credits(self, usage: HardwareUsage) -> float:
        """根据沙箱 CPU/内存规格权重和运行秒数计算硬件算力积分。"""
        # 规格系数：以 2C/4G 为基准 1.0
        spec_factor = (usage.cpu_cores / 2.0) * 0.5 + (usage.memory_gb / 4.0) * 0.5
        time_credits = usage.execution_seconds * self.BASE_HARDWARE_CREDITS_PER_SEC * spec_factor
        io_credits = (usage.volume_read_mb + usage.volume_write_mb) * self.VOLUME_IO_CREDITS_PER_MB
        return time_credits + io_credits

    def calculate_cognitive_credits(self, usage: CognitiveUsage) -> float:
        """根据 Prompt、Completion 与 Caching 折算认知算力积分。"""
        non_cached_prompt = max(0, usage.prompt_tokens - usage.cached_prompt_tokens)
        prompt_cost = (non_cached_prompt / 1000.0) * self.PROMPT_CREDITS_PER_1K
        cached_cost = (usage.cached_prompt_tokens / 1000.0) * self.CACHED_PROMPT_CREDITS_PER_1K
        completion_cost = (usage.completion_tokens / 1000.0) * self.COMPLETION_CREDITS_PER_1K
        return prompt_cost + cached_cost + completion_cost

    def generate_task_report(
        self,
        task_id: str,
        hardware: HardwareUsage,
        cognitive: CognitiveUsage,
        circuit_breaker: BudgetCircuitBreaker | None = None,
    ) -> HybridLedgerReport:
        """生成任务综合全景对账单。"""
        hw_credits = self.calculate_hardware_credits(hardware)
        hardware.hardware_credits = hw_credits

        cog_credits = self.calculate_cognitive_credits(cognitive)
        cognitive.cognitive_credits = cog_credits

        total_credits = hw_credits + cog_credits
        estimated_cost = total_credits * self.CREDITS_TO_USD_RATE

        is_exceeded = False
        exceeded_reason = ""
        if circuit_breaker is not None:
            is_exceeded, exceeded_reason = circuit_breaker.check(
                hardware=hardware,
                cognitive=cognitive,
                total_credits=total_credits,
            )

        return HybridLedgerReport(
            task_id=task_id,
            hardware=hardware,
            cognitive=cognitive,
            total_credits=total_credits,
            estimated_cost_usd=estimated_cost,
            is_budget_exceeded=is_exceeded,
            budget_exceeded_reason=exceeded_reason,
        )
