"""Skill sync protocols.

[INPUT]
- .types::RemoteSkillEntry, PushResult, PullResult, GateVerdict, ConflictResolution, ConflictStrategy

[OUTPUT]
- SkillSyncProtocol: Backend-agnostic skill sync interface
- SkillQualityGateProtocol: Pluggable quality gate for push validation

[POS]
Protocol definitions for skill synchronization. Framework layer defines these;
business layer (server) or downstream integrators provide implementations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import (
    ConflictResolution,
    ConflictStrategy,
    GateVerdict,
    PullResult,
    PushResult,
    RemoteSkillEntry,
)


@runtime_checkable
class SkillSyncProtocol(Protocol):
    """Backend-agnostic skill synchronization interface.

    Implementations:
    - LocalFSSyncBackend: file-system-based (Local/Tauri multi-device)
    - HTTPSyncBackend: HTTP-based (SaaS via control-plane)

    The protocol intentionally works with skill *bundles* (ZIP bytes)
    so that the sync layer is decoupled from SkillStore internals.
    """

    async def push_skills(
        self,
        bundles: dict[str, bytes],
    ) -> PushResult:
        """Push locally evolved skills to the shared repository.

        Args:
            bundles: Mapping of {skill_name: zip_bytes} produced by SkillPacker.

        Returns:
            PushResult with per-skill gate verdicts.
        """
        ...

    async def pull_skills(
        self,
        since_version: str = "",
        name_filter: str = "",
    ) -> PullResult:
        """Pull updated skills from the shared repository.

        Args:
            since_version: Only return skills updated after this version/timestamp.
            name_filter: Optional prefix filter (e.g. "data-processing/").

        Returns:
            PullResult with new/updated skill bundles stored locally.
        """
        ...

    async def list_remote(
        self,
        prefix: str = "",
    ) -> list[RemoteSkillEntry]:
        """List skills available in the shared repository.

        Args:
            prefix: Optional name prefix filter.

        Returns:
            List of lightweight remote skill descriptors.
        """
        ...

    async def resolve_conflict(
        self,
        skill_name: str,
        local_sha256: str,
        remote_sha256: str,
        strategy: ConflictStrategy = ConflictStrategy.NEWER_WINS,
    ) -> ConflictResolution:
        """Resolve a conflict between local and remote skill versions.

        Args:
            skill_name: Name of the conflicting skill.
            local_sha256: SHA256 of local version.
            remote_sha256: SHA256 of remote version.
            strategy: Resolution strategy to apply.

        Returns:
            ConflictResolution describing how the conflict was resolved.
        """
        ...


@runtime_checkable
class SkillQualityGateProtocol(Protocol):
    """Pluggable quality gate for skill push validation.

    Evaluated before pushing a skill to the shared repository.
    Inspired by SkillClaw's skill_verifier.py 4-dimension verification,
    but as a Protocol so different implementations can be plugged in.

    Default framework implementation: threshold-based (effective_rate >= 0.7).
    Business layer can provide LLM-based multi-dimension verification.
    """

    async def evaluate(
        self,
        skill_name: str,
        skill_content: str,
        effective_rate: float,
        total_executions: int,
    ) -> GateVerdict:
        """Evaluate whether a skill meets quality criteria for sharing.

        Args:
            skill_name: Name of the skill being evaluated.
            skill_content: Full SKILL.md content.
            effective_rate: Success rate (success_count / applied_count).
            total_executions: Total number of executions for statistical confidence.

        Returns:
            GateVerdict with pass/fail and reasons.
        """
        ...
