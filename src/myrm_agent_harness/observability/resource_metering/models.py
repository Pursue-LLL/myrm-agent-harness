"""
[INPUT]
- Python 标准库 dataclasses, time, typing

[OUTPUT]
- HardwareUsage: 物理机器与沙箱执行硬件占用模型
- CognitiveUsage: 模型 Token 与认知计算消耗模型
- HybridLedgerReport: 物理硬件占用与认知 Token 混合开销全景对账单

[POS]
myrm-agent-harness/src/myrm_agent_harness/observability/resource_metering/models.py — 混合算力计量与全景对账单数据模型。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class HardwareUsage:
    """沙箱物理硬件资源占用度量模型。"""

    execution_seconds: float = 0.0
    cpu_cores: float = 2.0
    memory_gb: float = 4.0
    volume_read_mb: float = 0.0
    volume_write_mb: float = 0.0
    hardware_credits: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """序列化为字典。"""
        return {
            "execution_seconds": round(self.execution_seconds, 2),
            "cpu_cores": round(self.cpu_cores, 2),
            "memory_gb": round(self.memory_gb, 2),
            "volume_read_mb": round(self.volume_read_mb, 2),
            "volume_write_mb": round(self.volume_write_mb, 2),
            "hardware_credits": round(self.hardware_credits, 4),
        }


@dataclass
class CognitiveUsage:
    """大模型认知 Token 消耗与计算度量模型。"""

    model_name: str = "default-llm"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    cognitive_credits: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """序列化为字典。"""
        return {
            "model_name": self.model_name,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_prompt_tokens": self.cached_prompt_tokens,
            "cognitive_credits": round(self.cognitive_credits, 4),
        }


@dataclass
class HybridLedgerReport:
    """单任务多维综合对账单汇总。"""

    task_id: str
    hardware: HardwareUsage
    cognitive: CognitiveUsage
    total_credits: float = 0.0
    estimated_cost_usd: float = 0.0
    is_budget_exceeded: bool = False
    budget_exceeded_reason: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """序列化为统一对账单 JSON 字典。"""
        return {
            "task_id": self.task_id,
            "hardware": self.hardware.to_dict(),
            "cognitive": self.cognitive.to_dict(),
            "total_credits": round(self.total_credits, 4),
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "is_budget_exceeded": self.is_budget_exceeded,
            "budget_exceeded_reason": self.budget_exceeded_reason,
            "created_at": self.created_at,
        }
