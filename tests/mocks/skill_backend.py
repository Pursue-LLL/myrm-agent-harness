"""In-memory skill backend for testing."""

from myrm_agent_harness.backends.skills.types import SkillMetadata


class InMemorySkillBackend:
    """In-memory implementation of SkillBackend for testing.

    This backend stores skills in dictionaries, making it fast and
    suitable for unit tests without filesystem or database dependencies.

    Example:
        >>> backend = InMemorySkillBackend()
        >>> backend.add_skill(SkillMetadata(name="test_skill", ...))
        >>> skills = await backend.load_skills(["test_skill"])
        >>> content = await backend.get_skill_content("test_skill")
    """

    def __init__(self) -> None:
        """Initialize empty skill storage."""
        self._skills: dict[str, SkillMetadata] = {}
        self._contents: dict[str, str] = {}
        self._resources: dict[str, dict[str, bytes]] = {}

    def add_skill(
        self,
        skill: SkillMetadata,
        content: str = "",
        resources: dict[str, bytes] | None = None,
    ) -> None:
        """Add a skill to the backend (test helper).

        Args:
            skill: Skill metadata
            content: SKILL.md content
            resources: Resource files (path -> content)
        """
        self._skills[skill.name] = skill
        self._contents[skill.name] = content or f"# {skill.name}\n\n{skill.description}"
        self._resources[skill.name] = resources or {}

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        """Load skill metadata from memory.

        Args:
            skill_ids: List of skill IDs to load

        Returns:
            List of skill metadata

        Raises:
            ValueError: If a skill ID is not found
        """
        result = []
        for skill_id in skill_ids:
            if skill_id not in self._skills:
                raise ValueError(f"Skill not found: {skill_id}")
            result.append(self._skills[skill_id])
        return result

    async def get_skill_content(self, skill_name: str) -> str:
        """Get skill content from memory.

        Args:
            skill_name: Name of the skill

        Returns:
            SKILL.md content

        Raises:
            ValueError: If skill is not found
        """
        if skill_name not in self._contents:
            raise ValueError(f"Skill content not found: {skill_name}")
        return self._contents[skill_name]

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        """Get skill resource from memory.

        Args:
            skill_name: Name of the skill
            path: Relative path to the resource file

        Returns:
            File content as bytes

        Raises:
            ValueError: If skill or resource is not found
        """
        if skill_name not in self._resources:
            raise ValueError(f"Skill not found: {skill_name}")

        skill_resources = self._resources[skill_name]
        if path not in skill_resources:
            raise ValueError(f"Resource not found: {path}")

        return skill_resources[path]

    async def list_skills(self) -> list[SkillMetadata]:
        return list(self._skills.values())

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        if skill_name not in self._resources:
            return []
        return list(self._resources[skill_name].keys())

    def clear(self) -> None:
        """Clear all skills (useful for test cleanup)."""
        self._skills.clear()
        self._contents.clear()
        self._resources.clear()

    def get_all_skills(self) -> dict[str, SkillMetadata]:
        """Get all skills (useful for assertions)."""
        return self._skills.copy()
