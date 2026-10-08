"""Strongly typed contracts for project instruction modes and managed precedence.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- InstructionMode: Execution mode governing project instruction discovery and filtering.
- SettingsScope: Authority scope hierarchy for instruction mode configuration.
- InstructionSettings: Configured instruction settings originating from a specific scope.
- ResolvedPrecedence: Outcome of resolving instruction mode across hierarchical authority scopes.
- PrecedenceAuditReceipt: Audit receipt detailing precedence evaluation and filtering decisions.

[POS]
Strongly typed contracts for project instruction modes and managed precedence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InstructionMode(str, Enum):
    """Execution mode governing project instruction discovery and filtering."""

    ALL_MERGED = "all_merged"
    FALLBACK_DEFAULT = "fallback_default"
    ONLY_CLAUDE = "only_claude"
    ONLY_AGENTS = "only_agents"
    ONLY_MANAGED = "only_managed"


class SettingsScope(str, Enum):
    """Authority scope hierarchy for instruction mode configuration."""

    MANAGED_SETTINGS = "managed_settings"
    USER_SETTINGS = "user_settings"
    CLI_FLAGS = "cli_flags"
    REPO_CONFIG = "repo_config"


@dataclass(frozen=True)
class InstructionSettings:
    """Configured instruction settings originating from a specific scope."""

    mode: InstructionMode
    scope: SettingsScope
    managed_instructions: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedPrecedence:
    """Outcome of resolving instruction mode across hierarchical authority scopes."""

    effective_mode: InstructionMode
    origin_scope: SettingsScope
    repo_override_rejected: bool
    effective_managed_instructions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PrecedenceAuditReceipt:
    """Audit receipt detailing precedence evaluation and filtering decisions."""

    effective_mode: InstructionMode
    origin_scope: SettingsScope
    repo_override_rejected: bool
    total_scanned_rules: int
    retained_rules_count: int
    suppressed_rules_count: int
    audit_notes: str
