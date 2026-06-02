"""History tracking skill write backend.

[INPUT]
- myrm_agent_harness.backends.skills.creation_protocols::SkillWriteBackend, (POS: SkillBackend SkillDiscoveryBackend SkillBackend)
- myrm_agent_harness.backends.skills.protocols::SkillBackend (POS: Protocols for Skill Optimization Subsystem)
- .protocols::SkillHistoryBackend (POS: Protocols for Skill Optimization Subsystem)
- .types::SkillHistoryRecord, (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)

[OUTPUT]
- HistoryTrackingSkillWriteBackend: Wrapper service with automatic history tracking

[POS]
Framework-layer wrapper that adds history tracking to skill write operations.
Implements the Decorator pattern: intercepts all modification operations,
records history with context (thread_id/session_id), then delegates
to the inner write backend.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from myrm_agent_harness.agent.skills.discovery.sanitizer import SKILL_MD_FILE
from myrm_agent_harness.backends.skills.creation_protocols import (
    SkillDeleteResult,
    SkillResourceWriteResult,
    SkillSaveResult,
    SkillWriteBackend,
)
from myrm_agent_harness.backends.skills.protocols import SkillBackend

from .protocols import SkillHistoryBackend
from .types import SkillHistoryRecord, SkillRollbackResult

logger = logging.getLogger(__name__)


class HistoryTrackingSkillWriteBackend:
    """Framework-layer wrapper that adds history tracking to skill operations.

    Wraps SkillWriteBackend and automatically records history for all
    modification operations. By abstracting the reads via SkillBackend,
    it remains decoupled from actual filesystem paths.

    Args:
        read_backend: Read backend for previous content
        write_backend: Inner write backend for execution
        history_backend: History storage backend
    """

    def __init__(
        self,
        read_backend: SkillBackend,
        write_backend: SkillWriteBackend,
        history_backend: SkillHistoryBackend,
    ) -> None:
        self._read = read_backend
        self._write = write_backend
        self._history = history_backend

    async def save_skill(
        self,
        name: str,
        content: str,
        description: str = "",
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        user_agent: str | None = None,
    ) -> SkillSaveResult:
        """Save skill with automatic history tracking."""
        # Try to get previous content
        try:
            prev_content = await self._read.get_skill_content(name)
        except Exception:
            prev_content = None

        result = await self._write.save_skill(name, content, description)

        if result.success:
            await self._record_history(
                skill_name=name,
                action="save",
                file_path=f"{name}/{SKILL_MD_FILE}",
                prev_content=prev_content,
                new_content=content,
                thread_id=thread_id,
                session_id=session_id,
                request_id=request_id,
                user_agent=user_agent,
            )

        return result

    async def delete_skill(
        self,
        name: str,
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        user_agent: str | None = None,
    ) -> SkillDeleteResult:
        """Delete skill with automatic history tracking."""
        try:
            prev_content = await self._read.get_skill_content(name)
        except Exception:
            prev_content = None

        result = await self._write.delete_skill(name)

        if result.success:
            await self._record_history(
                skill_name=name,
                action="delete",
                file_path=f"{name}/{SKILL_MD_FILE}",
                prev_content=prev_content,
                new_content=None,
                thread_id=thread_id,
                session_id=session_id,
                request_id=request_id,
                user_agent=user_agent,
            )

        return result

    async def write_resource(
        self,
        skill_name: str,
        resource_path: str,
        content: str,
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        user_agent: str | None = None,
    ) -> SkillResourceWriteResult:
        """Write resource file with automatic history tracking."""
        try:
            prev_bytes = await self._read.get_skill_resources(skill_name, resource_path)
            prev_content = prev_bytes.decode("utf-8") if isinstance(prev_bytes, bytes) else prev_bytes
        except Exception:
            prev_content = None

        result = await self._write.write_resource(skill_name, resource_path, content)

        if result.success:
            await self._record_history(
                skill_name=skill_name,
                action="write_file",
                file_path=f"{skill_name}/{resource_path}",
                prev_content=prev_content,
                new_content=content,
                thread_id=thread_id,
                session_id=session_id,
                request_id=request_id,
                user_agent=user_agent,
            )

        return result

    async def delete_resource(
        self,
        skill_name: str,
        resource_path: str,
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        user_agent: str | None = None,
    ) -> SkillResourceWriteResult:
        """Delete resource file with automatic history tracking."""
        try:
            prev_bytes = await self._read.get_skill_resources(skill_name, resource_path)
            prev_content = prev_bytes.decode("utf-8") if isinstance(prev_bytes, bytes) else prev_bytes
        except Exception:
            prev_content = None

        result = await self._write.delete_resource(skill_name, resource_path)

        if result.success:
            await self._record_history(
                skill_name=skill_name,
                action="remove_file",
                file_path=f"{skill_name}/{resource_path}",
                prev_content=prev_content,
                new_content=None,
                thread_id=thread_id,
                session_id=session_id,
                request_id=request_id,
                user_agent=user_agent,
            )

        return result

    async def list_history(
        self,
        skill_name: str,
        limit: int = 100,
    ) -> list[SkillHistoryRecord]:
        """List skill modification history."""
        return await self._history.list_history(skill_name, limit)

    async def rollback_to_version(
        self,
        skill_name: str,
        history_index: int = -1,
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        user_agent: str | None = None,
    ) -> SkillRollbackResult:
        """Rollback skill to a previous version."""
        records = await self._history.list_history(skill_name, limit=1000)
        if not records:
            return SkillRollbackResult(
                success=False,
                skill_name=skill_name,
                error=f"No history found for skill: {skill_name}",
            )

        try:
            target_record = records[history_index]
        except IndexError:
            return SkillRollbackResult(
                success=False,
                skill_name=skill_name,
                error=f"Invalid history_index: {history_index} (total: {len(records)})",
            )

        # Extract content to restore
        if target_record.prev_content is None:
            # Create operation - restore to the created version
            if target_record.new_content is None:
                return SkillRollbackResult(
                    success=False,
                    skill_name=skill_name,
                    error="Selected history entry has neither previous nor new content",
                )
            target_content = target_record.new_content
        else:
            target_content = target_record.prev_content

        # Conflict detection
        if history_index < -1:
            newer_records_count = abs(history_index) - 1
            newer_records = records[:newer_records_count]
            real_modifications = [r for r in newer_records if r.action != "rollback"]

            if real_modifications:
                most_recent = real_modifications[0]
                conflict_msg = (
                    f"Conflict detected: {len(real_modifications)} modification(s) occurred after target version. "
                    f"Most recent: {most_recent.action} by {most_recent.author} at {most_recent.timestamp.isoformat()}. "
                    f"Rolling back will overwrite these changes. "
                    f"Hint: Review history and consider using history_index=-1 to roll back to the most recent version first."
                )
                return SkillRollbackResult(
                    success=False,
                    skill_name=skill_name,
                    error=conflict_msg,
                )

        current_content = await self._read.get_skill_content(skill_name)

        # Use save_skill to restore
        result = await self.save_skill(
            name=skill_name,
            content=target_content,
            thread_id=thread_id,
            session_id=session_id,
            request_id=request_id,
            user_agent=user_agent,
        )

        if not result.success:
            return SkillRollbackResult(success=False, skill_name=skill_name, error=result.error)

        # Record rollback as a separate history entry
        await self._record_history(
            skill_name=skill_name,
            action="rollback",
            file_path=f"{skill_name}/{SKILL_MD_FILE}",
            prev_content=current_content,
            new_content=target_content,
            thread_id=thread_id,
            session_id=session_id,
            request_id=request_id,
            user_agent=user_agent,
            metadata={"rolled_back_to": target_record.timestamp.isoformat()},
        )

        logger.warning(
            "Rolled back skill '%s' to version %s (thread=%s)",
            skill_name,
            target_record.timestamp,
            thread_id,
        )

        return SkillRollbackResult(
            success=True,
            skill_name=skill_name,
            skill_id=f"local::{skill_name}",
            rolled_back_to=target_record.timestamp,
        )

    async def _record_history(
        self,
        skill_name: str,
        action: str,
        file_path: str,
        prev_content: str | None,
        new_content: str | None,
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Record a history entry with business context."""
        author = "agent" if thread_id else "human"

        record = SkillHistoryRecord(
            action=action,
            author=author,
            timestamp=datetime.now(UTC),
            file_path=file_path,
            prev_content=prev_content,
            new_content=new_content,
            thread_id=thread_id,
            session_id=session_id,
            request_id=request_id,
            user_agent=user_agent,
            metadata=metadata,
        )

        try:
            await self._history.append_history(skill_name, record)
        except Exception as e:
            logger.warning("Failed to record history for %s: %s", skill_name, e)
