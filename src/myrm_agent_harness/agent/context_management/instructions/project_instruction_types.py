"""Data types and schemas for workspace project instruction auto-ingestion.

[INPUT]
- dataclasses::dataclass, field (POS: Python 数据类标准库)
- enum::IntEnum (POS: Python 整型枚举标准库)

[OUTPUT]
- InstructionPriorityTier: 分层指令优先级枚举
- DiscoveredInstructionFile: 发现的项目指令文件记录
- ProjectInstructionConfig: 指令嗅探与截断配置
- ProjectInstructionIngestResult: 项目指令摄入诊断与前端 HUD 契约
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class InstructionPriorityTier(IntEnum):
    """Hierarchical instruction priority ordering (lower value = base layer, higher value = override)."""

    USER_GLOBAL = 10
    AGENT_PROFILE = 20
    WORKSPACE_PROJECT = 30
    TURN_PROMPT = 40


@dataclass(frozen=True, slots=True)
class DiscoveredInstructionFile:
    """Diagnostic detail of a single discovered project rule file."""

    path: str
    filename: str
    content: str
    char_count: int


@dataclass(frozen=True, slots=True)
class ProjectInstructionConfig:
    """Configuration for discovering and sanitizing workspace instruction files."""

    search_filenames: tuple[str, ...] = (
        "AGENTS.md",
        "agents.md",
        "MYRM.md",
        "myrm.md",
        ".myrm/rules.md",
        ".cursorrules",
        "CLAUDE.md",
        "claude.md",
        "SOUL.md",
        "soul.md",
        "MEMORY.md",
        "memory.md",
    )
    max_file_chars: int = 12000
    max_total_chars: int = 30000
    strip_zero_width_chars: bool = True


@dataclass(frozen=True, slots=True)
class ProjectInstructionIngestResult:
    """Diagnostic outcome of workspace project instruction auto-ingestion."""

    workspace_root: str
    has_active_instructions: bool
    active_files: list[str]
    total_chars: int
    badge_label: str
    formatted_prompt_block: str
    discovered_files: list[DiscoveredInstructionFile] = field(default_factory=list)
