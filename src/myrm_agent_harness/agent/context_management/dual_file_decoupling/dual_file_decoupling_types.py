"""Strongly typed contracts for Static Rule AGENTS.md and Dynamic Status Overview Suite (Item 217).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- ProjectRuleInvariantSpec: Immutable system rules parsed from AGENTS.md.
- DynamicOverviewSections: Strongly typed 5-section operational state parsed from 00_项目总览.md.
- DualFileContextEnvelope: Dual-channel decoupled context payload ready for prompt assembly.
- DualFileDecouplingConfig: Tunable configurations for file paths, formatting, and validation.

[POS]
- Eliminates prompt bloating and rule confusion by strictly decoupling static system rules
- from fast-moving project milestone status into a physical two-file architecture.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProjectRuleInvariantSpec:
    """Strongly typed specification of static, unshakeable rules from AGENTS.md."""

    rule_source_path: str
    raw_content: str
    core_principles: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    sha256_hash: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serializes static rule invariant to dictionary."""
        return {
            "rule_source_path": self.rule_source_path,
            "raw_content": self.raw_content,
            "core_principles": list(self.core_principles),
            "forbidden_actions": list(self.forbidden_actions),
            "sha256_hash": self.sha256_hash,
        }


@dataclass(frozen=True, slots=True)
class DynamicOverviewSections:
    """Standard 5-section active project dashboard representation."""

    current_phase_goal: str = ""
    established_facts: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    blockers_and_decisions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    last_updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes dynamic overview sections to dictionary."""
        return {
            "current_phase_goal": self.current_phase_goal,
            "established_facts": list(self.established_facts),
            "deliverables": list(self.deliverables),
            "blockers_and_decisions": list(self.blockers_and_decisions),
            "next_actions": list(self.next_actions),
            "last_updated_at": self.last_updated_at,
        }


@dataclass(frozen=True, slots=True)
class DualFileContextEnvelope:
    """Decoupled dual-channel context frames for assembly into agent conversations."""

    system_invariant_frame: str
    dynamic_status_frame: str
    rule_hash: str
    status_hash: str
    cached_invariant_tokens_estimate: int
    active_status_tokens_estimate: int

    def to_dict(self) -> dict[str, object]:
        """Serializes dual-file context envelope to dictionary."""
        return {
            "system_invariant_frame": self.system_invariant_frame,
            "dynamic_status_frame": self.dynamic_status_frame,
            "rule_hash": self.rule_hash,
            "status_hash": self.status_hash,
            "cached_invariant_tokens_estimate": self.cached_invariant_tokens_estimate,
            "active_status_tokens_estimate": self.active_status_tokens_estimate,
        }


@dataclass(slots=True)
class DualFileDecouplingConfig:
    """Configuration governing dual-file decoupling, paths, and formatting schemas."""

    enabled: bool = True
    static_rule_filename: str = "AGENTS.md"
    dynamic_status_filename: str = "00_项目总览.md"
    enforce_five_section_schema: bool = True
