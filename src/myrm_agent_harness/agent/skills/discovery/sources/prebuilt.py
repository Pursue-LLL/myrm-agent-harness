"""Prebuilt skill search source.

Searches locally installed prebuilt skills as the highest-priority discovery source.

[INPUT]
- backends.skills.discovery_protocols::SkillSearchResult (POS: SkillBackend SkillBackend SkillDiscoveryBackend)

[OUTPUT]
- PrebuiltSkillSource: Prebuilt skill data source.

[POS]
Prebuilt skill search source.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.backends.skills.discovery_protocols import SkillSearchResult

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.discovery_protocols import InstalledSkillStore

logger = logging.getLogger(__name__)


class PrebuiltSkillSource:
    """Prebuilt skill data source.

    Searches installed prebuilt skills by keyword matching against name/description/tags.
    Requires an InstalledSkillStore injected at construction time.
    """

    def __init__(self, skill_store: InstalledSkillStore) -> None:
        self._store = skill_store

    @property
    def source_name(self) -> str:
        return "prebuilt"

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        try:
            skills = await self._store.list_installed(skill_type="prebuilt")
        except Exception as e:
            logger.warning("Failed to list prebuilt skills: %s", e)
            return []

        keywords = query.lower().split()

        results: list[SkillSearchResult] = []
        for skill in skills:
            result = SkillSearchResult(
                id=skill.id,
                name=skill.name,
                description=skill.description,
                source="prebuilt",
                author="official",
                install_url="",
                install_method="direct",
                version=skill.version,
                tags=skill.tags,
            )
            if not keywords:
                results.append(result)
            else:
                score = _compute_match_score(skill.name, skill.description, skill.tags, keywords)
                if score > 0:
                    results.append(result)

        return results[:limit]

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        skill = await self._store.get_installed(skill_id)
        if not skill:
            return None
        return SkillSearchResult(
            id=skill.id,
            name=skill.name,
            description=skill.description,
            source="prebuilt",
            author="official",
            install_url="",
            install_method="direct",
            version=skill.version,
            tags=skill.tags,
        )


def _compute_match_score(name: str, description: str, tags: list[str], keywords: list[str]) -> int:
    """Keyword match score: name > tags > description."""
    score = 0
    name_lower = name.lower()
    desc_lower = description.lower()
    tags_lower = " ".join(tags).lower()

    for kw in keywords:
        if kw in name_lower:
            score += 10
        if kw in tags_lower:
            score += 5
        if kw in desc_lower:
            score += 2

    return score
