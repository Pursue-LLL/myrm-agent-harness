"""Scanning skill write backend — framework-level security wrapper.

[INPUT]
- creation_protocols::SkillWriteBackend, (POS: SkillBackend SkillDiscoveryBackend SkillBackend)
- scanning::scan_skill_content, (POS: Scan result cache layer. Stores scan results in Volume (~/.myrm/skill_scans/) to avoid redundant scanning. Critical for performance: 20x speedup for repeat scans. Cache key: SHA256 hash of skill content Cache location: ~/.myrm/skill_scans/{content_hash}.json Expiration: 60 days TTL (auto-cleanup on get))
- scanning.llm_auditor::SkillLLMAuditor (POS: Semantic-level threat detection layer. Catches threats that regex patterns cannot detect (e.g., multi-step exfiltration, social engineering, obfuscated intent). Operates on an "only-escalate" principle: LLM findings can only raise severity, never lower static scan results. Designed as an optional enhancement — when no LLM is available, the system gracefully falls back to pure regex scanning.)

[OUTPUT]
- ScanningSkillWriteBackend: security wrapper that enforces scanning before writes

[POS]
Framework-level security wrapper for SkillWriteBackend.
Wraps the actual business-layer backend and enforces:
1. Mandatory regex-based security scanning before every save (cannot be bypassed)
2. Optional LLM semantic audit (only-escalate: can raise severity, never lower)
3. REJECT-level findings block the write entirely
4. Scan report is attached to the result for Agent self-correction
5. Loader cache invalidation after successful writes/deletes
6. Path traversal protection for resource file operations
"""

from __future__ import annotations

import logging
import posixpath
from typing import TYPE_CHECKING

from myrm_agent_harness.backends.skills.creation_protocols import (
    SkillDeleteResult,
    SkillResourceWriteResult,
    SkillSaveResult,
    SkillWriteBackend,
)
from myrm_agent_harness.backends.skills.scanning import (
    SkillTrustRecommendation,
    format_scan_report,
    scan_skill_content,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.skills.runtime.loader import SkillMdLoader
    from myrm_agent_harness.backends.skills.scanning.llm_auditor import SkillLLMAuditor

logger = logging.getLogger(__name__)


class ScanningSkillWriteBackend:
    """Security wrapper that enforces scanning before all skill writes.

    This wrapper sits between the tool layer and the actual backend,
    ensuring that no skill content can be persisted without passing
    the security scanner. Even if the tool layer is bypassed or a
    new tool is added, the scanner still runs.

    When an LLM auditor is provided, it runs as a second pass after
    regex scanning. The LLM can only escalate findings (add new ones
    or raise severity), never downgrade static scan results.

    Architecture:
        tool_layer → ScanningSkillWriteBackend → actual_backend
                     ↑ regex scan + LLM audit     ↑ storage logic
    """

    def __init__(
        self,
        inner: SkillWriteBackend,
        loader: SkillMdLoader | None = None,
        llm_auditor: SkillLLMAuditor | None = None,
    ) -> None:
        self._inner = inner
        self._loader = loader
        self._llm_auditor = llm_auditor

    async def save_skill(
        self,
        name: str,
        content: str,
        user_id: str,
        description: str = "",
    ) -> SkillSaveResult:
        """Save skill with mandatory security scanning.

        Scanning flow:
        1. Run regex-based scan_skill_content() on the content
        2. If LLM auditor available, run semantic audit (only-escalate)
        3. If REJECT → return failure with scan report
        4. If UNTRUSTED/INSTALLED/TRUSTED → delegate to inner backend
        5. Attach scan report to result
        6. Invalidate loader cache on success
        """
        scan_result = scan_skill_content(name, content)

        if self._llm_auditor is not None:
            try:
                scan_result = await self._llm_auditor.audit(name, content, scan_result)
            except Exception:
                logger.warning("LLM audit failed for skill '%s', using static scan only", name, exc_info=True)

        report = format_scan_report(scan_result)

        if scan_result.trust_recommendation == SkillTrustRecommendation.REJECT:
            logger.warning("Skill '%s' rejected by security scanner: %s", name, scan_result.summary)
            return SkillSaveResult(
                success=False,
                skill_name=name,
                error=f"Security scan rejected this skill.\n\n{report}",
                scan_report=report,
            )

        try:
            result = await self._inner.save_skill(
                name=name,
                content=content,
                user_id=user_id,
                description=description,
            )
        except Exception as e:
            logger.error("Failed to save skill '%s': %s", name, e)
            return SkillSaveResult(
                success=False,
                skill_name=name,
                error=f"Storage error: {e}",
                scan_report=report,
            )

        if result.success:
            self._invalidate_cache(name)
            if not scan_result.is_clean:
                logger.warning("Skill '%s' saved with findings: %s", name, scan_result.summary)

        return SkillSaveResult(
            success=result.success,
            skill_name=result.skill_name,
            skill_id=result.skill_id,
            saved_path=result.saved_path,
            was_updated=result.was_updated,
            error=result.error,
            scan_report=report,
        )

    async def delete_skill(
        self,
        name: str,
        user_id: str,
    ) -> SkillDeleteResult:
        """Delete skill and invalidate cache."""
        try:
            result = await self._inner.delete_skill(name=name, user_id=user_id)
        except Exception as e:
            logger.error("Failed to delete skill '%s': %s", name, e)
            return SkillDeleteResult(success=False, skill_name=name, error=f"Storage error: {e}")

        if result.success:
            self._invalidate_cache(name)

        return result

    async def write_resource(
        self,
        skill_name: str,
        resource_path: str,
        content: str,
        user_id: str,
    ) -> SkillResourceWriteResult:
        """Write a resource file with mandatory path validation and content scanning.

        Security flow:
        1. Validate resource_path against allowed subdirectories
        2. Check for path traversal attacks
        3. Scan content for security threats
        4. If REJECT → block the write
        5. Delegate to inner backend
        6. Invalidate loader cache on success
        """
        path_error = _validate_resource_path(resource_path)
        if path_error:
            return SkillResourceWriteResult(
                success=False,
                skill_name=skill_name,
                resource_path=resource_path,
                error=path_error,
            )

        content_size = len(content.encode("utf-8"))
        if content_size > _MAX_RESOURCE_SIZE:
            return SkillResourceWriteResult(
                success=False,
                skill_name=skill_name,
                resource_path=resource_path,
                error=f"Content too large: {content_size:,} bytes (max {_MAX_RESOURCE_SIZE:,} bytes).",
            )

        scan_result = scan_skill_content(f"{skill_name}/{resource_path}", content)
        report = format_scan_report(scan_result)

        if scan_result.trust_recommendation == SkillTrustRecommendation.REJECT:
            logger.warning(
                "Resource '%s/%s' rejected by security scanner: %s",
                skill_name,
                resource_path,
                scan_result.summary,
            )
            return SkillResourceWriteResult(
                success=False,
                skill_name=skill_name,
                resource_path=resource_path,
                error=f"Security scan rejected this file.\n\n{report}",
                scan_report=report,
            )

        try:
            result = await self._inner.write_resource(
                skill_name=skill_name,
                resource_path=resource_path,
                content=content,
                user_id=user_id,
            )
        except Exception as e:
            logger.error("Failed to write resource '%s/%s': %s", skill_name, resource_path, e)
            return SkillResourceWriteResult(
                success=False,
                skill_name=skill_name,
                resource_path=resource_path,
                error=f"Storage error: {e}",
                scan_report=report,
            )

        if result.success:
            self._invalidate_cache(skill_name)

        return SkillResourceWriteResult(
            success=result.success,
            skill_name=result.skill_name,
            resource_path=result.resource_path,
            error=result.error,
            scan_report=report,
        )

    async def delete_resource(
        self,
        skill_name: str,
        resource_path: str,
        user_id: str,
    ) -> SkillResourceWriteResult:
        """Delete a resource file with mandatory path validation."""
        path_error = _validate_resource_path(resource_path)
        if path_error:
            return SkillResourceWriteResult(
                success=False,
                skill_name=skill_name,
                resource_path=resource_path,
                error=path_error,
            )

        try:
            result = await self._inner.delete_resource(
                skill_name=skill_name,
                resource_path=resource_path,
                user_id=user_id,
            )
        except Exception as e:
            logger.error("Failed to delete resource '%s/%s': %s", skill_name, resource_path, e)
            return SkillResourceWriteResult(
                success=False,
                skill_name=skill_name,
                resource_path=resource_path,
                error=f"Storage error: {e}",
            )

        if result.success:
            self._invalidate_cache(skill_name)

        return result

    def _invalidate_cache(self, skill_name: str) -> None:
        """Invalidate loader cache for the modified skill."""
        if self._loader is not None:
            self._loader.invalidate_skill(skill_name)
            logger.debug("Invalidated loader cache for skill '%s'", skill_name)


# ---------------------------------------------------------------------------
# Resource path validation (framework-level, cannot be bypassed)
# ---------------------------------------------------------------------------

_ALLOWED_RESOURCE_DIRS = frozenset({"references", "templates", "scripts", "assets"})

_MAX_RESOURCE_SIZE = 100 * 1024  # 100 KB


def _validate_resource_path(resource_path: str) -> str | None:
    """Validate resource path for security. Returns error message or None."""
    if not resource_path or not resource_path.strip():
        return "Resource path cannot be empty."

    normalized = posixpath.normpath(resource_path)

    if normalized.startswith("/") or normalized.startswith("\\"):
        return f"Absolute paths are not allowed: '{resource_path}'"

    if ".." in normalized.split("/"):
        return f"Path traversal detected: '{resource_path}'"

    if "\x00" in resource_path:
        return "Null bytes are not allowed in paths."

    parts = normalized.split("/")
    if not parts or parts[0] not in _ALLOWED_RESOURCE_DIRS:
        allowed = ", ".join(sorted(_ALLOWED_RESOURCE_DIRS))
        return (
            f"Resource path must start with an allowed subdirectory: {allowed}.\n"
            f"Example: 'scripts/analyze.py' or 'references/api_docs.md'"
        )

    if len(parts) < 2 or not parts[-1]:
        return "Resource path must include a filename (e.g. 'scripts/analyze.py')."

    return None
