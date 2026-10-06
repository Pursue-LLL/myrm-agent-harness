"""Type definitions for Project-Specific Goosehints and Hierarchical Instruction Hub.

Defines schemas for multi-tier instruction scoping (global, workspace, subpackage),
inheritance resolution strategies, and invisible Unicode security metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class InstructionTierKind(StrEnum):
    """Hierarchical tier level for instruction scoping."""

    GLOBAL_USER = "global_user"
    WORKSPACE_ROOT = "workspace_root"
    SUBDIRECTORY_PACKAGE = "subdirectory_package"


class InheritanceResolutionStrategy(StrEnum):
    """Strategy for resolving conflicts between ancestor and descendant instruction rules."""

    APPEND_INHERIT = "append_inherit"
    SCOPING_OVERRIDE = "scoping_override"


@dataclass(frozen=True)
class InstructionRuleEntry:
    """A single loaded instruction rule scoped to a specific hierarchy tier."""

    tier: InstructionTierKind
    source_path: str
    rule_name: str
    content: str
    char_count: int
    stripped_invisible_chars_count: int


@dataclass(frozen=True)
class HierarchicalInstructionBlock:
    """Aggregated, sanitized, and structured prompt instruction package."""

    resolved_rules: tuple[InstructionRuleEntry, ...]
    rendered_xml: str
    total_chars: int
    tier_counts: dict[str, int] = field(default_factory=dict)
