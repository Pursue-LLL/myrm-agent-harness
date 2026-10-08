"""Composite Skill Backend


[INPUT]
- protocols::SkillBackend, SkillBackendProtocol (POS: 技能后端协议)
- types::SkillMetadata (POS: 技能元数据类型)

[OUTPUT]
- CompositeSkillBackend: 混合技能后端（前缀直达指定后端；其余技能按 list_skills 同一优先级归属解析）

[POS]
Composite skill backend. A key with a route prefix addresses that route alone; any other key (skill metadata
carries bare names and storage ids) resolves to the backend that owns the skill, in the priority order
`list_skills` uses to settle duplicate names.

"""

import logging

from myrm_agent_harness.backends.skills.protocols import SkillBackend, SkillBackendProtocol
from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


class CompositeSkillBackend(SkillBackend):
    """混合技能后端（路由）

    - 带路由前缀的键（如 ``/user/my_skill``）只发往该前缀对应的后端。
    - 其余键（``list_skills`` 返回的技能名 / ``storage_skill_id`` 均不带前缀）依次询问各后端，
      顺序与 ``list_skills`` 的同名去重一致：后注册的路由优先，默认后端最后。
      因此被列出的技能一定能取回内容与资源。

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
        >>> # 请求 "/user/my_skill" -> 只发往 user_backend
        >>> # 请求 "my_skill" -> 依次询问 system_backend、user_backend、local_backend
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

    def _candidate_backends(self, skill_key: str) -> list[SkillBackendProtocol]:
        """Backends that may serve ``skill_key``, in resolution order."""
        for prefix, backend in self.sorted_routes:
            if skill_key.startswith(prefix):
                return [backend]
        candidates = list(reversed(self.routes.values()))
        if self.default is not None:
            candidates.append(self.default)
        return candidates

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
        """获取技能内容（实现 SkillBackend 协议）

        Args:
            skill_name: 技能名称或 ``storage_skill_id``

        Raises:
            ValueError: 未配置任何后端
            FileNotFoundError: 没有后端拥有该技能
        """
        backends = self._candidate_backends(skill_name)
        if not backends:
            msg = f"No backend found for skill: {skill_name}"
            raise ValueError(msg)

        for backend in backends:
            try:
                return await backend.get_skill_content(skill_name)
            except FileNotFoundError:
                continue
        msg = f"Skill not found in any backend: {skill_name}"
        raise FileNotFoundError(msg)

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        """获取技能资源文件（由拥有该技能的后端提供）

        Args:
            skill_name: 技能名称或 ``storage_skill_id``
            path: 资源文件相对路径

        Returns:
            文件内容（字节）

        Raises:
            ValueError: 未配置任何后端
            FileNotFoundError: 没有后端拥有该技能的此文件
        """
        backends = self._candidate_backends(skill_name)
        if not backends:
            msg = f"No backend found for skill: {skill_name}"
            raise ValueError(msg)

        for backend in backends:
            try:
                return await backend.get_skill_resources(skill_name, path)
            except FileNotFoundError:
                continue
        msg = f"Resource not found in any backend: {path} in skill '{skill_name}'"
        raise FileNotFoundError(msg)

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        """列出技能的资源文件（取第一个返回非空列表的后端）"""
        for backend in self._candidate_backends(skill_name):
            resources = await backend.list_skill_resources(skill_name)
            if resources:
                return resources
        return []
