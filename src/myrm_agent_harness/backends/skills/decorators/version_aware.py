"""Version-aware skill backend decorator.

Serves the activated version snapshot of a skill from a protocol-based snapshot
store and falls back to the filesystem baseline when no snapshot is activated.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

from myrm_agent_harness.backends.skills.protocols import (
    SkillBackend,
    SnapshotStoreProtocol,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)

# Identifies the current conversation for per-session accounting (e.g. permission usage logs)
session_id_var: ContextVar[str] = ContextVar("session_id", default="default_session")


class VersionAwareSkillBackend(SkillBackend):
    """Dynamic version routing backend.

    Wraps a standard SkillBackend and intercepts content retrieval to serve the
    activated version snapshot from a snapshot store.
    """

    def __init__(
        self,
        base_backend: SkillBackend,
        snapshot_store: SnapshotStoreProtocol | None = None,
    ):
        self.base_backend = base_backend
        self._snapshot_store = snapshot_store

    async def list_skills(self) -> list[SkillMetadata]:
        return await self.base_backend.list_skills()

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        return await self.base_backend.load_skills(skill_ids)

    async def get_skill_content(self, skill_name: str) -> str:
        """Get skill content with version awareness.

        Priority:
        1. Explicitly activated version snapshot
        2. Local file system baseline
        """
        if not self._snapshot_store:
            return await self.base_backend.get_skill_content(skill_name)

        try:
            active_version = await self._snapshot_store.get_active_version(skill_name)
            if active_version is not None:
                logger.debug(
                    "Serving active snapshot version for %s (v%d)",
                    skill_name,
                    int(getattr(active_version, "version", 0)),
                )
                return str(getattr(active_version, "content", ""))
        except Exception as e:
            logger.error("Zero-latency version routing failed for %s: %s", skill_name, e)

        return await self.base_backend.get_skill_content(skill_name)

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        return await self.base_backend.get_skill_resources(skill_name, path)

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        return await self.base_backend.list_skill_resources(skill_name)
