"""Engine filtering and synthesizing workspace rules according to resolved instruction mode.

[INPUT]
- agent.workspace_rules.scanner::RuleFile (POS: Workspace rule file discovery and loading.)
- agent.workspace_rules.instruction_precedence.precedence_types::InstructionMode, PrecedenceAuditReceipt,
  ResolvedPrecedence (POS: Strongly typed contracts for project instruction modes and managed precedence.)

[OUTPUT]
- InstructionFilterEngine: Filters discovered workspace rule files based on resolved instruction mode and
  managed policies.

[POS]
Engine filtering and synthesizing workspace rules according to resolved instruction mode.
"""

from __future__ import annotations

import os

from myrm_agent_harness.agent.workspace_rules.scanner import RuleFile

from .precedence_types import (
    InstructionMode,
    PrecedenceAuditReceipt,
    ResolvedPrecedence,
)

_CLAUDE_FILENAMES = frozenset({"claude.md", ".claude/claude.md"})
_AGENTS_FILENAMES = frozenset({"agents.md"})


def _is_claude_rule(rule: RuleFile) -> bool:
    basename = os.path.basename(rule.path).lower()
    return basename == "claude.md" or ".claude" in rule.path.lower()


def _is_agents_rule(rule: RuleFile) -> bool:
    basename = os.path.basename(rule.path).lower()
    return basename == "agents.md"


class InstructionFilterEngine:
    """Filters discovered workspace rule files based on resolved instruction mode and managed policies."""

    def filter_and_synthesize(
        self,
        scanned_rules: list[RuleFile],
        precedence: ResolvedPrecedence,
    ) -> tuple[list[RuleFile], PrecedenceAuditReceipt]:
        """Apply instruction mode filtering and synthesize top-priority managed instructions."""
        managed_rule_files: list[RuleFile] = []
        for idx, instruction in enumerate(precedence.effective_managed_instructions):
            managed_rule_files.append(
                RuleFile(
                    path=f"<managed_policy_{idx}>",
                    content=instruction.strip(),
                    source="MANAGED_SETTINGS",
                    truncated=False,
                    blocked=False,
                )
            )

        mode = precedence.effective_mode
        retained_local_rules: list[RuleFile] = []

        if mode == InstructionMode.ONLY_MANAGED:
            # Strictly ignore all local repository files
            retained_local_rules = []

        elif mode == InstructionMode.ONLY_CLAUDE:
            retained_local_rules = [r for r in scanned_rules if _is_claude_rule(r)]

        elif mode == InstructionMode.ONLY_AGENTS:
            retained_local_rules = [r for r in scanned_rules if _is_agents_rule(r)]

        elif mode == InstructionMode.FALLBACK_DEFAULT:
            claude_rules = [r for r in scanned_rules if _is_claude_rule(r)]
            if claude_rules:
                retained_local_rules = claude_rules
            else:
                agents_rules = [r for r in scanned_rules if _is_agents_rule(r)]
                retained_local_rules = agents_rules

        elif mode == InstructionMode.ALL_MERGED:
            retained_local_rules = list(scanned_rules)

        # Synthesize final list with managed rules placed first
        final_rules = managed_rule_files + retained_local_rules
        suppressed_count = len(scanned_rules) - len(retained_local_rules)

        receipt = PrecedenceAuditReceipt(
            effective_mode=mode,
            origin_scope=precedence.origin_scope,
            repo_override_rejected=precedence.repo_override_rejected,
            total_scanned_rules=len(scanned_rules),
            retained_rules_count=len(final_rules),
            suppressed_rules_count=suppressed_count,
            audit_notes=(
                f"Resolved mode '{mode.value}' via '{precedence.origin_scope.value}'. "
                f"Synthesized {len(managed_rule_files)} managed rule(s) and retained "
                f"{len(retained_local_rules)} of {len(scanned_rules)} local rule(s)."
            ),
        )

        return final_rules, receipt
