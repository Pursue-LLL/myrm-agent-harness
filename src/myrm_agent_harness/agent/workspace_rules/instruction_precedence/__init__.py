"""Project instructions multi-mode and managed precedence package.

[INPUT]
- agent.workspace_rules.instruction_precedence.instruction_filter_engine::InstructionFilterEngine (POS: Engine
  filtering and synthesizing workspace rules according to resolved instruction mode.)
-
  agent.workspace_rules.instruction_precedence.instruction_precedence_suite::ClaudeCodeProjectInstructionsPrecedenceSuite
  (POS: End-to-end suite orchestrating project instruction mode resolution, managed precedence, and
  filtering.)
- agent.workspace_rules.instruction_precedence.managed_precedence_resolver::ManagedPrecedenceResolver (POS:
  Precedence resolver enforcing managed settings supremacy and denying repository authority.)
- agent.workspace_rules.instruction_precedence.precedence_types::InstructionMode, InstructionSettings,
  PrecedenceAuditReceipt, ResolvedPrecedence, SettingsScope (POS: Strongly typed contracts for project
  instruction modes and managed precedence.)

[OUTPUT]
- Re-exports: ClaudeCodeProjectInstructionsPrecedenceSuite, InstructionFilterEngine, InstructionMode,
  InstructionSettings, ManagedPrecedenceResolver, PrecedenceAuditReceipt, ResolvedPrecedence, SettingsScope

[POS]
Project instructions multi-mode and managed precedence package.
"""

from __future__ import annotations

from .instruction_filter_engine import InstructionFilterEngine
from .instruction_precedence_suite import ClaudeCodeProjectInstructionsPrecedenceSuite
from .managed_precedence_resolver import ManagedPrecedenceResolver
from .precedence_types import (
    InstructionMode,
    InstructionSettings,
    PrecedenceAuditReceipt,
    ResolvedPrecedence,
    SettingsScope,
)

__all__ = [
    "ClaudeCodeProjectInstructionsPrecedenceSuite",
    "InstructionFilterEngine",
    "InstructionMode",
    "InstructionSettings",
    "ManagedPrecedenceResolver",
    "PrecedenceAuditReceipt",
    "ResolvedPrecedence",
    "SettingsScope",
]
