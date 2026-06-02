"""技能数据源 Protocol

[INPUT]
- backends.skills.discovery_protocols::SkillSearchResult (POS: SkillBackend SkillBackend SkillDiscoveryBackend)

[OUTPUT]
- SkillSource: class — Skill Source

[POS]
Provides SkillSource.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from myrm_agent_harness.backends.skills.discovery_protocols import SkillSearchResult


@runtime_checkable
class SkillSource(Protocol):
    """技能搜索数据源协议

    每个实现对应一个外部技能源（GitHub、skills.sh、本地预构建等）。
    SkillDiscoveryService 聚合多个 SkillSource 的结果。
    """

    @property
    def source_name(self) -> str:
        """数据源标识符（如 'github', 'skills_sh', 'prebuilt'）"""
        ...

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        """搜索技能

        Args:
            query: 搜索关键词
            limit: 最大返回数量

        Returns:
            搜索结果列表
        """
        ...

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        """获取技能详情

        Args:
            skill_id: 技能 ID

        Returns:
            技能详情，未找到返回 None
        """
        ...
