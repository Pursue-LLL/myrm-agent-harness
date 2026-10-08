"""Canonical workspace topology validator enforcing directory layout schemas.

[INPUT]
- Root path to an agent workspace (Path or str).

[OUTPUT]
- TopologyValidationReport containing canonical conformance status, health score,
  detected ecosystem, and actionable improvement hints.

[POS]
- Harness workspace rules in agent/workspace_rules/canonical_scaffolding/topology_validator.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .scaffolding_types import (
    TopologyValidationReport,
    WorkspaceEcosystemSource,
)


class TopologyValidator:
    """Validates an agent workspace directory against canonical scaffolding standards."""

    RECOMMENDED_TOPOLOGY_FILES: tuple[tuple[str, ...], ...] = (
        ("SOUL.md", "soul.md"),
        ("USER.md", "user.md"),
        ("MEMORY.md", "memory.md"),
        ("HEARTBEAT.md", "heartbeat.md"),
    )

    CANONICAL_DIRECTORIES: tuple[str, ...] = (
        "rules",
        "skills",
        "memory",
        "agents",
    )

    @classmethod
    def validate_workspace_topology(cls, root_path: str | Path) -> TopologyValidationReport:
        """Inspects directory structure and computes health metrics against canonical topology."""
        root = Path(root_path)
        if not root.exists() or not root.is_dir():
            return TopologyValidationReport(
                is_canonical=False,
                ecosystem_detected=WorkspaceEcosystemSource.GENERIC_PROJECT,
                missing_required_files=("workspace_directory_not_found",),
                health_score=0.0,
                actionable_hints=("Ensure the provided workspace root path exists and is a valid directory.",),
            )

        missing_recommended: list[str] = []
        found_recommended_count = 0

        for file_candidates in cls.RECOMMENDED_TOPOLOGY_FILES:
            found = any((root / candidate).is_file() for candidate in file_candidates)
            if found:
                found_recommended_count += 1
            else:
                missing_recommended.append(file_candidates[0])

        found_dirs_count = 0
        for dir_name in cls.CANONICAL_DIRECTORIES:
            if (root / dir_name).is_dir():
                found_dirs_count += 1

        # Infer ecosystem based on topology markers
        ecosystem = cls._detect_ecosystem_signature(root)

        total_criteria = len(cls.RECOMMENDED_TOPOLOGY_FILES) + len(cls.CANONICAL_DIRECTORIES)
        achieved_score = found_recommended_count + (found_dirs_count * 0.5)
        health_score = min(1.0, max(0.0, achieved_score / total_criteria))

        hints: list[str] = []
        if "SOUL.md" in missing_recommended:
            hints.append("Create a 'SOUL.md' file defining agent identity, persona voice, and ethical baseline.")
        if "MEMORY.md" in missing_recommended:
            hints.append("Add 'MEMORY.md' to store persistent operational lessons and project context.")
        if "HEARTBEAT.md" in missing_recommended:
            hints.append("Configure 'HEARTBEAT.md' to schedule proactive background review opportunities.")
        if found_dirs_count == 0:
            hints.append("Consider creating 'rules/', 'skills/', or 'agents/' directories for structured modularity.")

        is_canonical = (
            ecosystem == WorkspaceEcosystemSource.CANONICAL_MYRM
            or (found_recommended_count >= 2 and found_dirs_count >= 1)
        )

        return TopologyValidationReport(
            is_canonical=is_canonical,
            ecosystem_detected=ecosystem,
            missing_recommended_files=tuple(missing_recommended),
            missing_required_files=(),
            health_score=round(health_score, 2),
            actionable_hints=tuple(hints),
        )

    @classmethod
    def _detect_ecosystem_signature(cls, root: Path) -> WorkspaceEcosystemSource:
        """Quickly tags the directory with the closest matching agent ecosystem."""
        if (root / ".muse").is_dir() or (root / "muse.config.json").is_file():
            return WorkspaceEcosystemSource.META_MUSE
        if (root / "hermes.json").is_file() or (root / ".hermes").is_dir():
            return WorkspaceEcosystemSource.HERMES
        if (root / ".cursorrules").is_file() or (root / ".cursor" / "rules").is_dir() or (root / ".windsurfrules").is_file():
            return WorkspaceEcosystemSource.CURSOR_WINDSURF

        disk_names = {f.name for f in root.iterdir()} if root.is_dir() else set()
        if "soul.md" in disk_names and ((root / "skills").is_dir() or (root / "agents").is_dir()):
            return WorkspaceEcosystemSource.OPEN_CLAW
        if "SOUL.md" in disk_names and ((root / "MEMORY.md").is_file() or (root / "HEARTBEAT.md").is_file()):
            return WorkspaceEcosystemSource.CANONICAL_MYRM
        if (root / "soul.md").is_file() and ((root / "skills").is_dir() or (root / "agents").is_dir()):
            return WorkspaceEcosystemSource.OPEN_CLAW
        if (root / "SOUL.md").is_file() and ((root / "MEMORY.md").is_file() or (root / "HEARTBEAT.md").is_file()):
            return WorkspaceEcosystemSource.CANONICAL_MYRM
        return WorkspaceEcosystemSource.GENERIC_PROJECT
