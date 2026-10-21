"""Quarantine-aware skill backend decorator.

Filters out quarantined (is_active=False) skills at runtime.
This is the Hard Darwinian Quarantine final solution: Runtime State Filtering.
Filesystem is the code truth; database is the state truth — perfectly decoupled.
"""

import logging

from myrm_agent_harness.backends.skills.protocols import SkillBackend, SkillStateReader
from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


class QuarantineAwareSkillBackend(SkillBackend):
    """Quarantine-aware skill backend proxy.

    After the base SkillBackend returns skill lists, joins with the state store
    to filter out is_active=False skills, preventing Agent from loading quarantined
    skills (solves the "ghost quarantine" problem).
    """

    def __init__(self, base_backend: SkillBackend, state_reader: SkillStateReader):
        self._base = base_backend
        self._state_reader = state_reader

    async def list_skills(self) -> list[SkillMetadata]:
        skills = await self._base.list_skills()
        return self._filter_active(skills)

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        skills = await self._base.load_skills(skill_ids)
        return self._filter_active(skills)

    async def get_skill_content(self, skill_name: str) -> str:
        if not self._is_skill_active(skill_name):
            raise FileNotFoundError(f"Skill '{skill_name}' is quarantined and cannot be loaded.")
        return await self._base.get_skill_content(skill_name)

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        if not self._is_skill_active(skill_name):
            raise FileNotFoundError(f"Skill '{skill_name}' is quarantined and cannot be loaded.")
        return await self._base.get_skill_resources(skill_name, path)

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        if not self._is_skill_active(skill_name):
            return []
        if hasattr(self._base, "list_skill_resources"):
            return await self._base.list_skill_resources(skill_name)
        return []

    def _is_skill_active(self, skill_name: str) -> bool:
        try:
            return self._state_reader.is_skill_active(skill_name)
        except Exception as e:
            logger.error("Failed to check skill active status for %s: %s", skill_name, e)
            return True

    def _filter_active(self, skills: list[SkillMetadata]) -> list[SkillMetadata]:
        if not skills:
            return []

        filtered: list[SkillMetadata] = []
        for skill in skills:
            if self._is_skill_active(skill.name):
                filtered.append(skill)
            else:
                logger.warning(
                    "Skill '%s' is quarantined (is_active=False). Filtered out at runtime.",
                    skill.name,
                )
        return filtered
