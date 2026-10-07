"""Types and models for upward instruction.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- InstructionEcosystem: Supported ecosystem formats for project instructions.
- EcosystemPriority: Numerical priority rank across ecosystems (higher takes precedence).
- ScannedInstructionFile: Represents a discovered instruction file along the upward directory path.
- LegacySkillsDirectory: Discovered zero-migration skills directory from foreign ecosystem.
- UpwardResolutionResult: Comprehensive aggregation result of upward instruction discovery.

[POS]
Types and models for upward instruction.
"""

# ============================================================================
# # Upward Instruction Resolver & Legacy Ecosystem Migration Types (Item 148)
# # Strict typed contracts for recursive directory tree instruction discovery,
# # cross-tool hierarchy prioritization (MYRM > AGENTS > CLAUDE > CURSOR > CODEX),
# # and zero-migration legacy skills auto-mounting.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum


class InstructionEcosystem(StrEnum):
    """Supported ecosystem formats for project instructions."""

    MYRM = "myrm"  # Native MYRM.md or .myrm/rules.md
    AGENTS_MD = "agents_md"  # Hermes / OpenAI AGENTS.md
    CLAUDE_MD = "claude_md"  # Anthropic Claude Code CLAUDE.md
    CURSOR_RULES = "cursor_rules"  # Cursor .cursorrules or .cursor/rules
    CODEX_MD = "codex_md"  # OpenAI Codex CODEX.md


class EcosystemPriority(IntEnum):
    """Numerical priority rank across ecosystems (higher takes precedence)."""

    MYRM = 100
    AGENTS_MD = 80
    CLAUDE_MD = 60
    CURSOR_RULES = 40
    CODEX_MD = 20


@dataclass(slots=True)
class ScannedInstructionFile:
    """Represents a discovered instruction file along the upward directory path."""

    file_path: str
    directory_path: str
    depth: int  # 0 = current working directory, 1 = parent, 2 = grand-parent...
    ecosystem: InstructionEcosystem
    priority: int
    content: str
    file_size_bytes: int
    tokens_estimate: int

    def to_dict(self) -> dict[str, str | int]:
        """Serializes scanned instruction file to dictionary."""
        return {
            "file_path": self.file_path,
            "directory_path": self.directory_path,
            "depth": self.depth,
            "ecosystem": str(self.ecosystem),
            "priority": self.priority,
            "file_size_bytes": self.file_size_bytes,
            "tokens_estimate": self.tokens_estimate,
        }


@dataclass(slots=True)
class LegacySkillsDirectory:
    """Discovered zero-migration skills directory from foreign ecosystem."""

    ecosystem: InstructionEcosystem
    directory_path: str
    skills_count: int
    is_active: bool = True
    manifest_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UpwardResolutionResult:
    """Comprehensive aggregation result of upward instruction discovery."""

    start_dir: str
    root_boundary_dir: str
    scanned_files: list[ScannedInstructionFile] = field(default_factory=list)
    merged_instructions_markdown: str = ""
    total_tokens_estimate: int = 0
    legacy_skills_dirs: list[LegacySkillsDirectory] = field(default_factory=list)

    def to_dict(self) -> dict[str, str | int | list[dict[str, str | int]]]:
        """Converts result to structured dictionary payload."""
        return {
            "start_dir": self.start_dir,
            "root_boundary_dir": self.root_boundary_dir,
            "scanned_files_count": len(self.scanned_files),
            "total_tokens_estimate": self.total_tokens_estimate,
            "merged_instructions_preview": self.merged_instructions_markdown[:200],
            "legacy_skills_dirs_count": len(self.legacy_skills_dirs),
        }
