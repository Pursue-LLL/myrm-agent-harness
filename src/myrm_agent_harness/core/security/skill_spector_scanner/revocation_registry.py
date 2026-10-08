"""Skill Revocation Registry for supply chain takedowns and runtime blocking."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class SkillRevocationRegistry:
    """Thread-safe registry managing revoked or taken-down malicious skills."""

    def __init__(self) -> None:
        self._revoked_skills: dict[str, str] = {}
        self._lock: threading.Lock = threading.Lock()

    def revoke_skill(self, skill_id: str, reason: str) -> None:
        """Add a skill to the revocation list, blocking runtime dispatch."""
        with self._lock:
            self._revoked_skills[skill_id] = reason
            logger.warning("Skill '%s' has been REVOKED. Reason: %s", skill_id, reason)

    def is_revoked(self, skill_id: str) -> bool:
        """Check whether a skill is currently revoked."""
        with self._lock:
            return skill_id in self._revoked_skills

    def get_revocation_reason(self, skill_id: str) -> str | None:
        """Get the revocation reason for a skill if revoked."""
        with self._lock:
            return self._revoked_skills.get(skill_id)

    def unrevoke_skill(self, skill_id: str) -> bool:
        """Reinstate a skill previously revoked."""
        with self._lock:
            if skill_id in self._revoked_skills:
                del self._revoked_skills[skill_id]
                logger.info("Skill '%s' reinstated.", skill_id)
                return True
            return False

    def list_revoked(self) -> dict[str, str]:
        """Return all revoked skills and their reasons."""
        with self._lock:
            return dict(self._revoked_skills)

    def clear_all(self) -> None:
        """Clear registry (test isolation)."""
        with self._lock:
            self._revoked_skills.clear()
