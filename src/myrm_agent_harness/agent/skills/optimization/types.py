"""Skill Optimization Types

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- enum.Enum (POS: Python标准枚举基类)
- typing.Protocol (POS: Python协议类型)
- dataclasses.dataclass (POS: Python数据类装饰器)
- contextlib.AsyncContextManager (POS: Python异步上下文管理器)

[OUTPUT]
- SkillType: Skill类型枚举 (PREBUILT/USER/WORKSPACE)
- LockProvider: 分布式锁提供者协议
- SkillQualityScore: 5维Skill质量评分
- SecurityValidationResult: 安全验证结果
- OptimizationStatus: 优化状态枚举
- ABTestStatus: A/B测试状态枚举
- OptimizationResult: 优化结果
- ABTestResult: A/B测试结果
- SkillVersion: Skill版本记录

[POS]
Skill optimization system core type definitions. Provides type-safe data structures and protocol interfaces.

"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class SkillType(StrEnum):
    """Skill类型枚举

    用于区分skill的存储范围和并发控制需求：
    - PREBUILT: 全局共享，需要跨进程锁 (Cross-Process Lock)
    - USER: per-user隔离，不需要锁
    - WORKSPACE: per-workspace隔离，不需要锁
    """

    PREBUILT = "prebuilt"
    USER = "user"
    WORKSPACE = "workspace"


class LockProvider(Protocol):
    """并发锁提供者协议 (Concurrency Lock Provider)

    针对单机架构提供跨多进程、多线程的并发访问保护。
    框架提供协议定义，单机默认实现通常为 FileLock。
    """

    async def acquire(self, key: str, timeout: float = 30.0) -> AbstractAsyncContextManager[None]:
        """获取并发锁

        Args:
            key: 锁的唯一标识（如skill:opt:skill_name）
            timeout: 锁超时时间（秒）

        Returns:
            异步上下文管理器

        Raises:
            LockAcquisitionError: 获取锁失败
        """
        ...


@dataclass
class SkillQualityScore:
    """5维Skill质量评分 + 成本追踪

    综合评估Skill质量的5个关键指标：
    1. success_rate: 成功率（0-1）
    2. token_efficiency: Token效率（tokens per call的倒数归一化）
    3. execution_time: 执行时间（秒的倒数归一化）
    4. user_satisfaction: 用户满意度（0-1，基于点赞/点踩 + 隐式反馈）
    5. call_frequency: 调用频率（归一化）

    成本追踪字段：
    - prompt_tokens: LLM调用的输入token数
    - completion_tokens: LLM调用的输出token数
    - total_tokens: 总token数（prompt + completion）
    - llm_cost_usd: LLM调用成本（美元）
    """

    success_rate: float  # 0-1
    token_efficiency: float  # 0-1
    execution_time: float  # 0-1 (normalized inverse)
    user_satisfaction: float  # 0-1
    call_frequency: float  # 0-1 (normalized)

    # 成本追踪字段
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_cost_usd: float = 0.0

    @property
    def overall_score(self) -> float:
        """综合评分（加权平均）"""
        weights = {
            "success_rate": 0.3,
            "token_efficiency": 0.2,
            "execution_time": 0.2,
            "user_satisfaction": 0.2,
            "call_frequency": 0.1,
        }
        return (
            self.success_rate * weights["success_rate"]
            + self.token_efficiency * weights["token_efficiency"]
            + self.execution_time * weights["execution_time"]
            + self.user_satisfaction * weights["user_satisfaction"]
            + self.call_frequency * weights["call_frequency"]
        )


@dataclass
class SecurityValidationResult:
    """安全验证结果"""

    passed: bool
    issues: list[str]  # 安全问题列表

    @property
    def is_safe(self) -> bool:
        """是否安全"""
        return self.passed and len(self.issues) == 0


class OptimizationStatus(StrEnum):
    """优化状态枚举"""

    PENDING = "pending"  # 等待中
    IN_PROGRESS = "in_progress"  # 进行中
    TESTING = "testing"  # A/B测试中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    ROLLED_BACK = "rolled_back"  # 已回滚


class ABTestStatus(StrEnum):
    """A/B测试状态枚举"""

    RUNNING = "running"  # 运行中
    BASELINE_WIN = "baseline_win"  # 基线版本胜出
    CANDIDATE_WIN = "candidate_win"  # 候选版本胜出
    NO_DIFFERENCE = "no_difference"  # 无显著差异
    FAILED = "failed"  # 测试失败
    STOPPED = "stopped"  # 提前停止


@dataclass
class OptimizationResult:
    """优化结果"""

    skill_id: str
    skill_type: SkillType
    baseline_score: SkillQualityScore
    optimized_content: str
    security_validation: SecurityValidationResult
    status: OptimizationStatus
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    version: int | None = None  # 优化后生成的版本号（如果已保存）


@dataclass
class SkillVersion:
    """Skill版本

    记录skill的每个版本，支持版本回滚。
    """

    skill_id: str
    version: int  # 版本号，从1开始递增
    content: str  # Skill内容
    quality_score: SkillQualityScore | None  # 该版本的质量评分（可能未评估）
    created_at: datetime
    created_by: str  # "llm" | "manual" | "rollback"
    optimization_id: str | None = None  # 关联的优化ID（如果是LLM优化产生的）
    is_active: bool = False  # 是否为当前激活版本
    metadata: dict | None = None  # 额外元数据


@dataclass
class ABTestResult:
    """A/B测试结果"""

    skill_id: str
    baseline_version: int
    candidate_version: int
    baseline_score: SkillQualityScore
    candidate_score: SkillQualityScore
    sample_size: int
    status: ABTestStatus
    started_at: datetime
    completed_at: datetime | None = None
    winner: str | None = None  # "baseline" | "candidate" | None


class LockAcquisitionError(Exception):
    """获取锁失败异常"""

    pass


class OptimizationError(Exception):
    """优化失败异常"""

    pass


class SecurityError(Exception):
    """安全验证失败异常"""

    pass


class VersionConflictError(Exception):
    """版本冲突异常"""

    pass
