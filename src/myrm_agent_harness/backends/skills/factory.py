"""Skill Backend Factory

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- protocols::SkillBackend (POS: 技能后端协议)
- local::LocalSkillBackend (POS: 本地技能后端实现)
- storage::StorageSkillBackend (POS: 存储技能后端实现)
- memory::InMemorySkillBackend (POS: 内存技能后端实现)
- composite::CompositeSkillBackend (POS: 混合技能后端实现)

[OUTPUT]
- SkillBackend: 技能后端工厂类（提供 local(), storage(), memory(), composite() 静态方法）

[POS]
Skill backend factory. Provides convenient factory methods for creating various backends (local, storage, memory, composite).

"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.protocols import SkillBackend as SkillBackendProtocol
    from myrm_agent_harness.backends.skills.types import SkillTrust
    from myrm_agent_harness.toolkits.storage.base import StorageProvider


class SkillBackend:
    """技能后端工厂

    提供便捷方法创建各种技能后端。

    Example:
        >>> # 本地技能
        >>> local_backend = SkillBackend.local("./my_skills")
        >>>
        >>> # 存储技能
        >>> storage_backend = StorageBackend.local("./workspace")
        >>> skill_backend = SkillBackend.storage(storage_backend, skills_prefix="/skills")
        >>>
        >>> # 混合路由
        >>> composite = SkillBackend.composite(
        ...     routes={
        ...         "/user/": local_backend,
        ...         "/system/": skill_backend,
        ...     },
        ...     default=local_backend,
        ... )
    """

    @staticmethod
    def local(skills_dir: str | Path) -> "SkillBackendProtocol":
        """创建本地技能后端

        Args:
            skills_dir: 技能目录路径

        Returns:
            LocalSkillBackend 实例
        """
        from myrm_agent_harness.backends.skills import LocalSkillBackend

        return LocalSkillBackend(skills_dir)

    @staticmethod
    def storage(
        storage: "StorageProvider",
        skills_prefix: str = "/skills",
        default_trust: "SkillTrust | None" = None,
    ) -> "SkillBackend":
        """创建存储技能后端

        Args:
            storage: 存储后端实例
            skills_prefix: 技能存储路径前缀
            default_trust: Trust level for loaded skills (default INSTALLED)

        Returns:
            StorageSkillBackend 实例
        """
        from myrm_agent_harness.backends.skills import StorageSkillBackend

        if default_trust is not None:
            return StorageSkillBackend(storage, skills_prefix, default_trust=default_trust)
        return StorageSkillBackend(storage, skills_prefix)

    @staticmethod
    def composite(
        routes: dict[str, "SkillBackendProtocol"],
        default: "SkillBackendProtocol | None" = None,
    ) -> "SkillBackendProtocol":
        """创建混合技能后端（路由）

        Args:
            routes: 路由映射（前缀 -> 后端）
            default: 默认后端（可选）

        Returns:
            CompositeSkillBackend 实例
        """
        from myrm_agent_harness.backends.skills import CompositeSkillBackend

        return CompositeSkillBackend(routes, default)


__all__ = ["SkillBackend"]
