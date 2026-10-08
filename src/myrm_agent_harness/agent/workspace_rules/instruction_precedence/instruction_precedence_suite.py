"""End-to-end suite orchestrating project instruction mode resolution, managed precedence, and filtering.

[INPUT]
- agent.workspace_rules.scanner::RuleFile (POS: Workspace rule file discovery and loading.)
- agent.workspace_rules.instruction_precedence.instruction_filter_engine::InstructionFilterEngine (POS: Engine
  filtering and synthesizing workspace rules according to resolved instruction mode.)
- agent.workspace_rules.instruction_precedence.managed_precedence_resolver::ManagedPrecedenceResolver (POS:
  Precedence resolver enforcing managed settings supremacy and denying repository authority.)
- agent.workspace_rules.instruction_precedence.precedence_types::InstructionMode, InstructionSettings,
  PrecedenceAuditReceipt, ResolvedPrecedence (POS: Strongly typed contracts for project instruction modes and
  managed precedence.)

[OUTPUT]
- ClaudeCodeProjectInstructionsPrecedenceSuite: Industrial-grade suite implementing 4-mode project instruction
  filtering with managed precedence.

[POS]
End-to-end suite orchestrating project instruction mode resolution, managed precedence, and filtering.
"""

from __future__ import annotations

from myrm_agent_harness.agent.workspace_rules.scanner import RuleFile

from .instruction_filter_engine import InstructionFilterEngine
from .managed_precedence_resolver import ManagedPrecedenceResolver
from .precedence_types import (
    InstructionMode,
    InstructionSettings,
    PrecedenceAuditReceipt,
    ResolvedPrecedence,
)


class ClaudeCodeProjectInstructionsPrecedenceSuite:
    """Industrial-grade suite implementing 4-mode project instruction filtering with managed precedence."""

    def __init__(
        self,
        resolver: ManagedPrecedenceResolver | None = None,
        filter_engine: InstructionFilterEngine | None = None,
    ) -> None:
        """Initialize precedence suite."""
        self._resolver: ManagedPrecedenceResolver = resolver or ManagedPrecedenceResolver()
        self._filter_engine: InstructionFilterEngine = filter_engine or InstructionFilterEngine()

    @property
    def resolver(self) -> ManagedPrecedenceResolver:
        """Access underlying precedence resolver."""
        return self._resolver

    @property
    def filter_engine(self) -> InstructionFilterEngine:
        """Access underlying filter engine."""
        return self._filter_engine

    def resolve_and_filter_rules(
        self,
        scanned_rules: list[RuleFile],
        managed_settings: InstructionSettings | None = None,
        user_settings: InstructionSettings | None = None,
        cli_flags: InstructionSettings | None = None,
        repo_settings: InstructionSettings | None = None,
    ) -> tuple[list[RuleFile], PrecedenceAuditReceipt]:
        """Resolve precedence across authority scopes and filter scanned workspace rules.

        1. Evaluates settings precedence: Managed > User > CLI.
        2. Strictly denies repository settings any authority to set or override instruction mode.
        3. Filters scanned rules and synthesizes top-priority managed instructions.
        """
        precedence: ResolvedPrecedence = self._resolver.resolve_precedence(
            managed_settings=managed_settings,
            user_settings=user_settings,
            cli_flags=cli_flags,
            repo_settings=repo_settings,
        )

        return self._filter_engine.filter_and_synthesize(
            scanned_rules=scanned_rules,
            precedence=precedence,
        )

    @staticmethod
    def parse_mode(mode_str: str) -> InstructionMode:
        """Parse string value into strongly typed InstructionMode safely defaulting to ALL_MERGED."""
        normalized = mode_str.strip().lower()
        for mode in InstructionMode:
            if mode.value == normalized:
                return mode
        return InstructionMode.ALL_MERGED
