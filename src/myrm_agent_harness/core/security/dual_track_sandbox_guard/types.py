"""Domain types and models for Dual-Track Soft Memory vs Hard Redline Sandbox Guard Suite.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing cognitive tracks, hard redline rules,
  compiled physical sandbox firewall policies, and execution interception verdicts.

[POS]
- Harness core security domain models ensuring physical decoupling between soft fading
  memories and non-bypassable hard sandbox firewall execution invariants.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class CognitionTrack(StrEnum):
    """Cognitive layer classification."""

    SOFT_MEMORY = "SOFT_MEMORY"
    HARD_REDLINE = "HARD_REDLINE"


class RedlineCategory(StrEnum):
    """Protected boundary domain for a hard redline rule."""

    FILE_PROTECTION = "FILE_PROTECTION"
    COMMAND_PROTECTION = "COMMAND_PROTECTION"
    NETWORK_EGRESS = "NETWORK_EGRESS"
    PRIVILEGE_ESCALATION = "PRIVILEGE_ESCALATION"


class InterceptionVerdict(StrEnum):
    """Final decision evaluated by the sandbox execution firewall."""

    PERMITTED = "PERMITTED"
    BLOCKED_HARD_REDLINE_FILE = "BLOCKED_HARD_REDLINE_FILE"
    BLOCKED_HARD_REDLINE_COMMAND = "BLOCKED_HARD_REDLINE_COMMAND"
    BLOCKED_EVASION_ATTEMPT = "BLOCKED_EVASION_ATTEMPT"


@dataclass(frozen=True)
class SoftMemoryRecord:
    """Soft experience memory: allows fuzzy retrieval, weight decay, and forgetting."""

    memory_id: str
    content: str
    recall_weight: float = 1.0
    decay_rate: float = 0.05
    last_accessed: float = field(default_factory=time.time)
    tags: tuple[str, ...] = field(default_factory=tuple)

    def compute_effective_weight(self, now: float | None = None) -> float:
        """Compute decayed recall weight over time elapsed."""
        current_time = now if now is not None else time.time()
        elapsed_hours = max(0.0, (current_time - self.last_accessed) / 3600.0)
        decay_factor = max(0.1, 1.0 - (self.decay_rate * elapsed_hours))
        return self.recall_weight * decay_factor


@dataclass(frozen=True)
class HardRedlineRule:
    """Deterministic, immutable security redline compiled directly into sandbox firewall."""

    rule_id: str
    category: RedlineCategory
    pattern: str
    description: str
    severity: str = "CRITICAL"
    is_immutable: bool = True
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class CompiledSandboxFirewallPolicy:
    """Compiled sandbox policy ready for deterministic syscall / process table gating."""

    blocked_file_patterns: tuple[str, ...]
    blocked_command_regexes: tuple[str, ...]
    rule_count: int
    enforced_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ExecutionInterceptionVerdict:
    """Outcome of pre-execution evaluation against compiled sandbox firewall."""

    verdict: InterceptionVerdict
    is_permitted: bool
    blocked_by_rule_id: str | None
    target_operation: str
    audit_id: str
    rationale: str
