"""Version-aware skill backend decorator.

Implements zero-latency A/B testing and version switching using protocol-based
storage injection. Supports:
- Forced version override (shadow testing)
- Active A/B test routing (sticky session-based)
- Activated version snapshot serving
- Filesystem baseline fallback
"""

from __future__ import annotations

import hashlib
import logging
from contextvars import ContextVar

from myrm_agent_harness.backends.skills.protocols import (
    ABTestStoreProtocol,
    SkillBackend,
    SnapshotStoreProtocol,
    resolved_skill_versions_var,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)

# Request context for A/B testing stickiness
session_id_var: ContextVar[str] = ContextVar("session_id", default="default_session")
# Forced version for shadow testing or specific version benchmarking
forced_version_var: ContextVar[int | None] = ContextVar("forced_version", default=None)


class VersionAwareSkillBackend(SkillBackend):
    """Dynamic version routing backend.

    Wraps a standard SkillBackend and intercepts content retrieval to inject
    optimized versions or A/B test candidates from a snapshot store.
    """

    def __init__(
        self,
        base_backend: SkillBackend,
        snapshot_store: SnapshotStoreProtocol | None = None,
        ab_test_store: ABTestStoreProtocol | None = None,
    ):
        self.base_backend = base_backend
        self._snapshot_store = snapshot_store
        self._ab_test_store = ab_test_store

    async def list_skills(self) -> list[SkillMetadata]:
        return await self.base_backend.list_skills()

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        return await self.base_backend.load_skills(skill_ids)

    async def get_skill_content(self, skill_name: str) -> str:
        """Get skill content with version awareness.

        Priority:
        1. Active A/B Test (Sticky version selection)
        2. Explicitly Activated Version Snapshot
        3. Local File System Baseline
        """
        if not self._snapshot_store:
            return await self.base_backend.get_skill_content(skill_name)

        # 0. Forced version override (High priority, for Shadow Testing)
        forced = forced_version_var.get()
        if forced is not None:
            snapshot = await self._snapshot_store.get_version(skill_name, forced)
            if snapshot is not None:
                logger.debug("Serving forced version for %s (v%d)", skill_name, forced)
                return str(getattr(snapshot, "content", ""))

        try:
            # 1. Check for Active A/B Tests for this skill
            if self._ab_test_store:
                running_tests = await self._ab_test_store.get_running_tests()
                matching_test = next(
                    (t for t in running_tests if getattr(t, "skill_id", None) == skill_name),
                    None,
                )

                if matching_test is not None:
                    session_id = session_id_var.get()
                    is_candidate = self._resolve_sticky(session_id, skill_name)

                    version_id = (
                        getattr(matching_test, "candidate_version", 0)
                        if is_candidate
                        else getattr(matching_test, "baseline_version", 0)
                    )

                    logger.info(
                        "A/B test active for %s: serving v%s (category=%s, session=%s)",
                        skill_name,
                        version_id,
                        "candidate" if is_candidate else "baseline",
                        session_id[:8],
                    )

                    snapshot = await self._snapshot_store.get_version(skill_name, int(version_id))
                    if snapshot is not None:
                        versions = (resolved_skill_versions_var.get() or {}).copy()
                        versions[skill_name] = int(version_id)
                        resolved_skill_versions_var.set(versions)
                        return str(getattr(snapshot, "content", ""))

                    if not is_candidate:
                        logger.debug("Baseline snapshot missing for %s v%s, falling back to disk", skill_name, version_id)
                        return await self.base_backend.get_skill_content(skill_name)

            # 2. Check for "Active" Persistent Versions (Optimized results)
            active_version = await self._snapshot_store.get_active_version(skill_name)
            if active_version is not None:
                av_ver = int(getattr(active_version, "version", 0))
                logger.debug("Serving active snapshot version for %s (v%d)", skill_name, av_ver)
                versions = (resolved_skill_versions_var.get() or {}).copy()
                versions[skill_name] = av_ver
                resolved_skill_versions_var.set(versions)
                return str(getattr(active_version, "content", ""))

        except Exception as e:
            logger.error("Zero-latency version routing failed for %s: %s", skill_name, e)

        # 3. Final Fallback: Local File System
        return await self.base_backend.get_skill_content(skill_name)

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        return await self.base_backend.get_skill_resources(skill_name, path)

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        return await self.base_backend.list_skill_resources(skill_name)

    def _resolve_sticky(self, session_id: str, skill_id: str, split: int = 50) -> bool:
        """Hash-based deterministic variant selection."""
        key = f"{session_id}:{skill_id}".encode()
        h = hashlib.md5(key).hexdigest()
        val = int(h[:8], 16) % 100
        return val < split
