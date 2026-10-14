"""Protocols for Skill Version History

Defines the storage interface the business layer implements.

[INPUT]
- .types::SkillVersion (POS: Skill version record)

[OUTPUT]
- SkillOptimizationStorage: class — Skill version history storage
- StorageError: class — Storage Error

[POS]
Skill version storage protocol (framework defines, server implements)
"""

from __future__ import annotations

from typing import Protocol

from .types import SkillVersion


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

    # ==================== SkillVersion ====================

    async def save_skill_version(
        self,
        skill_id: str,
        version: int,
        content: str,
        created_by: str = "llm",
        optimization_id: str | None = None,
        metadata: dict | None = None,
    ) -> SkillVersion:
        """保存Skill版本

        Args:
            skill_id: Skill ID
            version: 版本号
            content: Skill内容
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


class StorageError(Exception):
    """存储层错误基类"""

    pass
