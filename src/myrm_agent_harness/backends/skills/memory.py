"""In-Memory Skill Backend


[INPUT]
- protocols::SkillBackend (POS: 技能后端协议)
- types::SkillMetadata (POS: 技能元数据类型)

[OUTPUT]
- InMemorySkillBackend: 内存技能后端（存储动态生成的技能）

[POS]
In-memory skill backend. Stores skill metadata in memory without persistence.

"""

from myrm_agent_harness.backends.skills.protocols import SkillBackend
from myrm_agent_harness.backends.skills.types import SkillMetadata


class InMemorySkillBackend(SkillBackend):
    """内存技能后端

    存储在内存中的技能元数据，适用于：
    - MCP 技能（动态生成）
    - 临时技能（运行时创建）
    - 测试场景

    Note:
        此后端不持久化技能数据，仅在内存中保存。
        适合存储 MCP 技能等动态生成的技能。

    Example:
        >>> skills = [SkillMetadata(name="mcp_filesystem", description="...")]
        >>> backend = InMemorySkillBackend(skills=skills)
    """

    def __init__(self, skills: list[SkillMetadata]):
        """初始化内存后端

        Args:
            skills: 技能元数据列表
        """
        self.skills = skills
        self._skills_by_name = {skill.name: skill for skill in skills}

    async def get_skill_metadata(self, skill_name: str) -> SkillMetadata | None:
        """获取技能元数据

        Args:
            skill_name: 技能名称

        Returns:
            技能元数据，如果不存在则返回 None
        """
        return self._skills_by_name.get(skill_name)

    async def list_skills(self) -> list[SkillMetadata]:
        """列出所有技能元数据

        Returns:
            技能元数据列表
        """
        return self.skills.copy()

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        """按 ID 加载技能元数据

        Args:
            skill_ids: 技能 ID 列表（匹配 name 或 storage_skill_id）

        Returns:
            匹配的技能元数据列表
        """
        id_set = set(skill_ids)
        return [s for s in self.skills if s.name in id_set or s.storage_skill_id in id_set]

    async def get_skill_content(self, skill_name: str) -> str:
        """获取技能内容（MCP 技能动态生成）

        Args:
            skill_name: 技能名称

        Returns:
            SKILL.md 内容

        Raises:
            FileNotFoundError: 技能不存在
        """
        skill = self._skills_by_name.get(skill_name)
        if not skill:
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        # MCP 技能：使用 MCPSkillGenerator 动态生成
        if skill.is_mcp_skill and skill.mcp:
            from myrm_agent_harness.agent.skills.mcp.core_generator import MCPSkillGenerator

            generator = MCPSkillGenerator()
            return generator.generate_skill_content(skill)

        raise FileNotFoundError(f"Skill content not available for: {skill_name}")

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        raise FileNotFoundError(f"MCP skill has no resource files: {skill_name}")

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        return []


__all__ = ["InMemorySkillBackend"]
