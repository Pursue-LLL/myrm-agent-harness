"""Skill backend protocols.


[INPUT]
- types::SkillMetadata (POS: 技能元数据类型定义)
- typing::Protocol (POS: Python 协议类型)

[OUTPUT]
- SkillBackend: 技能后端协议(定义 list_skills, load_skills, get_skill_content, get_skill_resources)

[POS]
Skill backend protocol definition. Specifies the unified interface for loading skills from multiple sources.

"""

from contextvars import ContextVar
from typing import Protocol

from myrm_agent_harness.backends.skills.types import SkillMetadata

# Tracks which skill version (if any) was resolved by the backend (e.g. for AB tests)
# Format: {skill_name: version_number}
resolved_skill_versions_var: ContextVar[dict[str, int] | None] = ContextVar("resolved_skill_versions", default=None)


class SkillBackend(Protocol):
    """Protocol for skill backend implementations.

    This protocol defines the interface for loading and accessing skills.
    Skills support progressive disclosure:
    1. list_skills() - List all available skills (Level 0: discovery)
    2. load_skills() - Load specific skills by IDs (Level 1: targeted loading)
    3. get_skill_content() - Get SKILL.md content (Level 2: on-demand)
    4. get_skill_resources() - Get additional files (Level 3: if needed)

    Example:
        >>> class MySkillBackend:
        ...     async def list_skills(self) -> list[SkillMetadata]:
        ...         # List all available skills
        ...         return [SkillMetadata(...)]
        ...
        ...     async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        ...         # Load specific skills by IDs
        ...         return [SkillMetadata(...)]
        ...
        ...     async def get_skill_content(self, skill_name: str) -> str:
        ...         # Return SKILL.md content
        ...         return "# My Skill\\n\\n..."
        ...
        ...     async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        ...         # Return additional resource files
        ...         return b"..."
    """

    async def list_skills(self) -> list[SkillMetadata]:
        """List all available skills (Level 0: discovery).

        Returns metadata for all skills available in this backend.
        Used by SkillAgent to discover available skills.

        Returns:
            List of all skill metadata
        """
        ...

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        """Load skill metadata (Level 1: lightweight).

        This should return only metadata, not full content.
        Content will be loaded on-demand via get_skill_content().

        Args:
            skill_ids: List of skill IDs to load

        Returns:
            List of skill metadata

        Raises:
            SkillNotFoundError: If a skill ID is not found
        """
        ...

    async def get_skill_content(self, skill_name: str) -> str:
        """Get skill content (Level 2: on-demand).

        Returns the SKILL.md content for the specified skill.
        This is called when the agent selects a skill to use.

        Args:
            skill_name: Name of the skill (must end with _skill)

        Returns:
            SKILL.md content (without YAML frontmatter)

        Raises:
            SkillNotFoundError: If skill is not found
        """
        ...

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        """Get a single skill resource file (Level 3: if needed).

        Args:
            skill_name: Name of the skill
            path: Relative path to the resource file

        Returns:
            File content as bytes

        Raises:
            FileNotFoundError: If resource is not found
        """
        ...

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        """List all resource file paths for a skill (excluding SKILL.md).

        Args:
            skill_name: Name of the skill

        Returns:
            List of relative file paths
        """
        ...


SkillBackendProtocol = SkillBackend


# ---------------------------------------------------------------------------
# Decorator dependency protocols
# ---------------------------------------------------------------------------


class SkillStateReader(Protocol):
    """Protocol for checking skill active/quarantine state.

    Used by QuarantineAwareSkillBackend to filter out quarantined skills.
    Implementations typically wrap a database (e.g. SkillStore SQLite).
    """

    def is_skill_active(self, skill_name: str) -> bool:
        """Return True if the skill is active (not quarantined)."""
        ...


class SnapshotStoreProtocol(Protocol):
    """Protocol for accessing skill version snapshots.

    Used by VersionAwareSkillBackend to serve optimized or A/B-tested versions.
    """

    async def get_version(self, skill_id: str, version: int) -> object | None:
        """Return the snapshot for a specific skill version, or None."""
        ...

    async def get_active_version(self, skill_id: str) -> object | None:
        """Return the currently activated snapshot for a skill, or None."""
        ...


class ABTestStoreProtocol(Protocol):
    """Protocol for accessing running A/B tests.

    Used by VersionAwareSkillBackend to route requests to candidate/baseline.
    """

    async def get_running_tests(self) -> list[object]:
        """Return all currently running A/B tests."""
        ...
