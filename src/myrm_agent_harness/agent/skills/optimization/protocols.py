"""Protocols for Skill Optimization Subsystem

Defines the storage and execution-provider interfaces the business layer implements.

[INPUT]
- backends.skills.types::SkillMetadata (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)

[OUTPUT]
- SkillOptimizationStorage: class — Skill Optimization Storage
- SkillExecutionProvider: class — Skill Execution Provider
- StorageError: class — Storage Error

[POS]
Storage and execution-provider protocols (framework defines, server implements)
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from myrm_agent_harness.backends.skills.types import SkillMetadata

from .quality_calculator import SkillExecutionSample
from .types import (
    ABTestResult,
    OptimizationResult,
    SkillQualityScore,
    SkillVersion,
)


class SkillOptimizationStorage(Protocol):
    """存储层抽象接口

    框架层定义接口, 业务层提供实现。
    支持多种后端: SQLAlchemy, MongoDB, Redis, 内存等。

    设计原则:
    1. 接口清晰: 所有方法明确定义输入输出
    2. 异步优先: 所有操作都是异步的
    3. 类型安全: 完整的类型提示
    4. 可测试性: 接口易于mock
    """

    # ==================== OptimizationRecord ====================

    async def save_optimization_record(self, record: OptimizationResult) -> None:
        """保存优化记录

        Args:
            record: 优化结果对象

        Raises:
            StorageError: 存储失败
        """
        ...

    async def get_optimization_record(self, skill_id: str) -> OptimizationResult | None:
        """获取最新优化记录

        Args:
            skill_id: Skill ID

        Returns:
            最新的优化记录, 不存在返回None
        """
        ...

    # ==================== ABTestResult ====================

    async def save_ab_test(self, result: ABTestResult) -> None:
        """保存A/B测试结果

        Args:
            result: A/B测试结果对象

        Raises:
            StorageError: 存储失败
        """
        ...

    async def get_ab_test(self, skill_id: str) -> ABTestResult | None:
        """获取正在运行的A/B测试

        Args:
            skill_id: Skill ID

        Returns:
            正在运行的A/B测试, 不存在返回None
        """
        ...

    async def get_running_ab_tests(self) -> list[ABTestResult]:
        """获取所有正在运行的A/B测试

        Returns:
            所有RUNNING状态的A/B测试列表
        """
        ...

    # ==================== SkillVersion ====================

    async def save_skill_version(
        self,
        skill_id: str,
        version: int,
        content: str,
        quality_score: SkillQualityScore | None = None,
        created_by: str = "llm",
        optimization_id: str | None = None,
        metadata: dict | None = None,
    ) -> SkillVersion:
        """保存Skill版本

        Args:
            skill_id: Skill ID
            version: 版本号
            content: Skill内容
            quality_score: 质量评分(可选)
            created_by: 创建方式("llm" | "manual" | "rollback")
            optimization_id: 关联的优化ID(可选)
            metadata: 额外元数据(可选)

        Returns:
            保存的SkillVersion对象

        Raises:
            StorageError: 存储失败
        """
        ...

    async def get_skill_version(self, skill_id: str, version: int) -> SkillVersion | None:
        """获取指定版本

        Args:
            skill_id: Skill ID
            version: 版本号

        Returns:
            SkillVersion对象, 不存在返回None
        """
        ...

    async def get_active_version(self, skill_id: str) -> SkillVersion | None:
        """获取当前激活版本

        Args:
            skill_id: Skill ID

        Returns:
            当前激活的SkillVersion, 不存在返回None
        """
        ...

    async def list_skill_versions(self, skill_id: str, limit: int = 50) -> list[SkillVersion]:
        """列出Skill所有版本

        Args:
            skill_id: Skill ID
            limit: 最大返回数量

        Returns:
            版本列表, 按版本号降序
        """
        ...

    async def activate_version(self, skill_id: str, version: int) -> SkillVersion:
        """激活指定版本(回滚)

        将指定版本设为active, 其他版本设为inactive。

        Args:
            skill_id: Skill ID
            version: 要激活的版本号

        Returns:
            激活的SkillVersion对象

        Raises:
            StorageError: 版本不存在或激活失败
        """
        ...

    async def delete_skill_versions(self, skill_id: str, keep_latest: int = 10) -> int:
        """删除旧版本

        保留最新N个版本和当前激活版本, 删除其余版本。

        Args:
            skill_id: Skill ID
            keep_latest: 保留最新N个版本

        Returns:
            删除的版本数
        """
        ...

    # ==================== SkillQualityHistory ====================

    async def save_quality_snapshot(self, skill_id: str, score: SkillQualityScore, version: int | None = None) -> None:
        """保存质量快照

        Args:
            skill_id: Skill ID
            score: 质量评分
            version: Skill版本号(可选)

        Raises:
            StorageError: 存储失败
        """
        ...

    async def get_quality_history(self, skill_id: str, days: int = 30) -> list[tuple[datetime, SkillQualityScore]]:
        """获取质量历史

        Args:
            skill_id: Skill ID
            days: 最近N天

        Returns:
            (时间戳, 质量评分)列表, 按时间倒序
        """
        ...

    async def get_latest_quality(self, skill_id: str) -> SkillQualityScore | None:
        """获取最新质量评分

        Args:
            skill_id: Skill ID

        Returns:
            最新质量评分, 不存在返回None
        """
        ...

    # ==================== Health Check ====================

    async def health_check(self) -> dict[str, bool | str]:
        """健康检查

        Returns:
            健康状态字典, 包含:
            - healthy: bool - 总体健康状态
            - storage_type: str - 存储类型
            - writable: bool - 是否可写
            - readable: bool - 是否可读
        """
        ...


class SkillExecutionProvider(Protocol):
    """Skill执行事件提供者接口

    框架层定义接口, 业务层提供实现。
    从各种事件源(EventLog, metrics, logs)查询skill执行数据。

    设计原则:
    1. 数据源无关: 可以是EventLog, Prometheus, files, etc.
    2. 流式接口: 支持大规模数据查询
    3. 时间范围: 所有查询都支持时间过滤
    """

    async def get_skill_executions(
        self, skill_id: str, days: int = 7, session_id: str | None = None
    ) -> list[SkillExecutionSample]:
        """获取skill执行样本

        Args:
            skill_id: Skill ID
            days: 最近N天的数据
            session_id: 可选的session过滤

        Returns:
            执行样本列表
        """
        ...

    async def get_all_skill_ids(self) -> list[str]:
        """获取所有有执行记录的skill ID

        Returns:
            Skill ID列表
        """
        ...

    async def count_executions(self, skill_id: str, days: int = 7) -> int:
        """统计执行次数

        Args:
            skill_id: Skill ID
            days: 最近N天

        Returns:
            执行次数
        """
        ...

    async def get_skill_metadata(self, skill_id: str) -> SkillMetadata | None:
        """获取skill元数据

        Args:
            skill_id: Skill ID

        Returns:
            SkillMetadata对象, 如果skill不存在则返回None
        """
        ...

    async def get_skill_content(self, skill_id: str) -> str | None:
        """获取skill源码内容 (SKILL.md)

        Args:
            skill_id: Skill ID

        Returns:
            Skill源码内容, 如果不存在返回None
        """
        ...


class StorageError(Exception):
    """存储层错误基类"""

    pass
