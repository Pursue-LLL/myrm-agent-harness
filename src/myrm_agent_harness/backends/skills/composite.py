"""Composite Skill Backend

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- protocols::SkillBackend, SkillBackendProtocol (POS: 技能后端协议)
- types::SkillMetadata (POS: 技能元数据类型)

[OUTPUT]
- CompositeSkillBackend: 混合技能后端（根据前缀路由到不同后端，支持回退）

[POS]
Composite skill backend. Routes requests to different backends based on skill name prefix with default fallback.

"""

import logging

from myrm_agent_harness.backends.skills.protocols import SkillBackend, SkillBackendProtocol
from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


class CompositeSkillBackend(SkillBackend):
    """混合技能后端（路由）

    根据技能名称前缀，将请求路由到不同的后端。

    类似 LangChain 的 CompositeBackend Router：
    https://docs.langchain.com/oss/python/deepagents/backends#compositebackend-router

    Example:
        >>> backend = CompositeSkillBackend(
        ...     routes={
        ...         "/user/": user_backend,
        ...         "/system/": system_backend,
        ...     },
        ...     default=local_backend,
        ... )
        >>>
        >>> # 请求 "/user/my_skill" -> 路由到 user_backend
        >>> # 请求 "/system/tool" -> 路由到 system_backend
        >>> # 请求 "other" -> 路由到 default backend
    """

    def __init__(
        self,
        routes: dict[str, SkillBackendProtocol],
        default: SkillBackendProtocol | None = None,
    ):
        """初始化

        Args:
            routes: 路由映射（前缀 -> 后端）
            default: 默认后端（未匹配时使用）
        """
        self.routes = routes
        self.default = default
        # 按前缀长度降序排序（最长匹配优先）
        self.sorted_routes = sorted(routes.items(), key=lambda x: len(x[0]), reverse=True)

    def _get_backend(self, skill_name: str) -> SkillBackendProtocol | None:
        """根据技能名称获取对应的后端"""
        for prefix, backend in self.sorted_routes:
            if skill_name.startswith(prefix):
                return backend
        return self.default

    async def list_skills(self) -> list[SkillMetadata]:
        """列出所有后端的技能（同名去重，后注册的后端优先）

        Deduplication strategy (agentskills.io "last wins"):
        - Skills from later backends override earlier ones with the same name
        - Traversal order: default backend -> route backends (in registration order)
        - This ensures user skills override prebuilt skills
        """
        # Use dict for dedup: later entries override earlier ones (last wins)
        skills_by_name: dict[str, SkillMetadata] = {}

        # 先加载默认后端（最低优先级）
        if self.default:
            try:
                skills = await self.default.list_skills()
                for skill in skills:
                    skills_by_name[skill.name] = skill
            except Exception as e:
                logger.warning(f"Failed to list skills from default backend: {e}")

        # 再加载路由后端（按注册顺序，后注册的优先级更高）
        for backend in self.routes.values():
            try:
                skills = await backend.list_skills()
                for skill in skills:
                    if skill.name in skills_by_name:
                        logger.warning(f"Skill '{skill.name}' overridden by later backend (last wins)")
                    skills_by_name[skill.name] = skill
            except Exception as e:
                logger.warning(f"Failed to list skills from backend: {e}")

        return list(skills_by_name.values())

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        """加载指定技能的元数据（同名去重，后注册的后端优先）

        Args:
            skill_ids: 技能 ID 列表

        Returns:
            技能元数据列表（去重后）
        """
        # Use dict for dedup: later entries override earlier ones (last wins)
        skills_by_name: dict[str, SkillMetadata] = {}

        # 先加载默认后端（最低优先级）
        if self.default:
            try:
                skills = await self.default.load_skills(skill_ids)
                for skill in skills:
                    skills_by_name[skill.name] = skill
            except Exception as e:
                logger.warning(f"Failed to load skills from default backend: {e}")

        # 再加载路由后端（按注册顺序，后注册的优先级更高）
        for backend in self.routes.values():
            try:
                skills = await backend.load_skills(skill_ids)
                for skill in skills:
                    skills_by_name[skill.name] = skill
            except Exception as e:
                logger.warning(f"Failed to load skills from backend: {e}")

        return list(skills_by_name.values())

    async def get_skill_content(self, skill_name: str) -> str:
        """获取技能内容（实现 SkillBackend 协议）"""
        backend = self._get_backend(skill_name)
        if not backend:
            msg = f"No backend found for skill: {skill_name}"
            raise ValueError(msg)

        return await backend.get_skill_content(skill_name)

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        """获取技能资源文件（路由到对应后端）

        Args:
            skill_name: 技能名称
            path: 资源文件相对路径

        Returns:
            文件内容（字节）

        Raises:
            ValueError: 找不到对应后端
            FileNotFoundError: 文件不存在
        """
        backend = self._get_backend(skill_name)
        if not backend:
            msg = f"No backend found for skill: {skill_name}"
            raise ValueError(msg)

        return await backend.get_skill_resources(skill_name, path)

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        backend = self._get_backend(skill_name)
        if not backend:
            return []
        return await backend.list_skill_resources(skill_name)
