# [INPUT]: ParsedRuleClause, RuleCallerContext
# [OUTPUT]: ExceptionAwareRuleParser
# [POS]: agent/workspace_rules/rule_governance/exception_aware_rule_parser.py

"""Parser and evaluator for exception-aware rule schemas in persistent workspace rules.

[INPUT]
- ParsedRuleClause: Decomposed rule representation with directive and exception branches.
- RuleCallerContext: Context of the action initiator (system watchdog, human user, cron).

[OUTPUT]
- ExceptionAwareRuleParser: Stateless engine parsing explicit exceptions and evaluating action permissions.

[POS]
Rule decomposition and exception matching layer in rule lifecycle governance.
"""

from __future__ import annotations

import re
from typing import Sequence

from .governance_types import ParsedRuleClause, RuleCallerContext


class ExceptionAwareRuleParser:
    """Parses rules containing explicit exception clauses and evaluates exemptions for system callers."""

    # Matches exception delimiters: 【例外】:, [EXCEPTION]:, UNLESS:, etc.
    _EXCEPTION_PATTERN = re.compile(
        r"(?:【(?:例外|豁免)】[：:]|\[(?:EXCEPTION|EXCEPT|WAIVER)\][：:]|(?:(?<=\s)UNLESS|(?<=\s)EXCEPT)[：:])",
        re.IGNORECASE,
    )

    _STRICT_KEYWORDS = ("严禁", "禁止", "不得", "必须", "never", "forbidden", "prohibited", "must not")
    _WATCHDOG_KEYWORDS = ("看门狗", "watchdog", "自愈", "自动恢复", "健康检查", "health check", "运维", "巡检")

    def parse_rule_clause(self, line: str, index: int = 0) -> ParsedRuleClause | None:
        """Parses a single line of text into a ParsedRuleClause, or None if not a rule."""
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None

        # Clean list markers (- , * , 1. , etc.)
        cleaned = re.sub(r"^(?:[-*+]|\d+\.)\s+", "", stripped)
        if not cleaned:
            return None

        parts = self._EXCEPTION_PATTERN.split(cleaned)
        core_directive = parts[0].strip()
        raw_exceptions = parts[1:]

        exceptions: list[str] = []
        for exc in raw_exceptions:
            # Further split by commas or semicolons if multiple conditions are listed
            sub_clauses = re.split(r"[;；,，]", exc)
            for sub in sub_clauses:
                trimmed = sub.strip()
                if trimmed:
                    exceptions.append(trimmed)

        directive_lower = core_directive.lower()
        is_strict = any(kw in directive_lower for kw in self._STRICT_KEYWORDS)

        rule_id = f"rule_{index:03d}"
        return ParsedRuleClause(
            rule_id=rule_id,
            raw_text=stripped,
            core_directive=core_directive,
            exceptions=tuple(exceptions),
            is_strict=is_strict,
        )

    def parse_document(self, content: str) -> Sequence[ParsedRuleClause]:
        """Parses full markdown document into list of structured rule clauses."""
        if not content:
            return ()

        clauses: list[ParsedRuleClause] = []
        for idx, line in enumerate(content.splitlines(), start=1):
            parsed = self.parse_rule_clause(line, index=idx)
            if parsed is not None:
                clauses.append(parsed)
        return tuple(clauses)

    def evaluate_action_permitted(
        self,
        clause: ParsedRuleClause,
        caller: RuleCallerContext,
        action_description: str,
    ) -> tuple[bool, str]:
        """Evaluates whether an action initiated by caller is permitted or blocked by the clause."""
        # Non-strict guidelines do not block automated actions
        if not clause.is_strict:
            return True, "Permitted: Advisory guideline."

        action_lower = action_description.lower()

        # Check if caller is system watchdog and rule explicitly mentions watchdog/recovery exceptions
        if caller.is_system_watchdog:
            for exc in clause.exceptions:
                exc_lower = exc.lower()
                if any(wk in exc_lower for wk in self._WATCHDOG_KEYWORDS):
                    return True, f"Exempted: Watchdog caller matches explicit exception '{exc}'."

        # Check if action description directly matches any explicit exception branch
        for exc in clause.exceptions:
            exc_lower = exc.lower()
            if exc_lower in action_lower or any(word in action_lower for word in exc_lower.split() if len(word) > 2):
                return True, f"Exempted: Action matches explicit exception '{exc}'."

        # Otherwise strict rule blocks action
        return False, f"Blocked: Action violates strict directive '{clause.core_directive}'."
