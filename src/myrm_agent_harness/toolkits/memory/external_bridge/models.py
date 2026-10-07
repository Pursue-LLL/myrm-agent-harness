# [POS] src/myrm_agent_harness/toolkits/memory/external_bridge/models.py
# [INPUT] typing (Enum, dataclass, Path, Optional, List, Dict)
# [OUTPUT] ExternalAgentType, SkillBridgeAction, SkillInstallConfig, SkillInstallResult, SkillUninstallResult, MemoryConflictReport

"""Data models and type definitions for external agent memory bridge and skill writing.

Provides standardized configuration contracts, execution results, and conflict detection
reports for external agent environments (Cursor, Claude Code, Codex, Hermes, OpenClaw).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ExternalAgentType(StrEnum):
    """Supported external agent coding assistants and runtimes."""

    CURSOR = "cursor"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    HERMES = "hermes"
    OPENCLAW = "openclaw"


class SkillBridgeAction(StrEnum):
    """Action outcome from a skill installation or update."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    UNINSTALLED = "uninstalled"
    CONFLICT_DETECTED = "conflict_detected"


@dataclass(frozen=True)
class SkillInstallConfig:
    """Configuration options for installing or updating memory bridge skill files."""

    agent_type: ExternalAgentType
    workspace_root: Path | None = None
    global_config: bool = False
    api_base_url: str = "http://127.0.0.1:8000"
    bridge_secret_token: str | None = None
    custom_target_path: Path | None = None
    read_only: bool = False
    max_recalled_facts: int = 8


@dataclass(frozen=True)
class SkillInstallResult:
    """Outcome of attempting to write or update an external agent bridge configuration."""

    agent_type: ExternalAgentType
    target_path: Path
    action: SkillBridgeAction
    marker_present: bool
    success: bool
    details: str = ""
    error: str | None = None


@dataclass(frozen=True)
class SkillUninstallResult:
    """Outcome of attempting to remove an external agent bridge configuration."""

    agent_type: ExternalAgentType
    target_path: Path
    removed: bool
    file_deleted: bool
    success: bool
    details: str = ""
    error: str | None = None


@dataclass(frozen=True)
class MemoryConflictReport:
    """Diagnostic report detailing conflicts with existing memory tools or prompt instructions."""

    has_conflict: bool
    conflicting_tools: list[str] = field(default_factory=list)
    conflicting_rules: list[str] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)
