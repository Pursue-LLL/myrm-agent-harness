"""Path-scoped and task-phase rule matching router for dynamic working set slicing.

Filters hundreds of system rules down to the exact relevant subset
based on file globs and current execution lifecycle phase.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.working_set_rules_types import (
    ActiveWorkingSet,
    RuleItem,
)


class PathScopedRuleMatcher:
    """Matches rules against active working paths and current task phase."""

    def match_rules(
        self,
        rules: Sequence[RuleItem],
        working_set: ActiveWorkingSet,
    ) -> list[RuleItem]:
        """Filter candidate rules to those relevant to the active working set."""
        matched: list[RuleItem] = []

        for rule in rules:
            if self._matches(rule, working_set):
                matched.append(rule)

        return matched

    def _matches(self, rule: RuleItem, working_set: ActiveWorkingSet) -> bool:
        """Check if a rule satisfies both task phase and path scope constraints."""
        # 1. Phase check
        if working_set.current_phase not in rule.applicable_phases:
            return False

        # If there are no active paths, only match generic rules that target all paths
        if not working_set.active_paths:
            return self._is_universal_rule(rule)

        # 2. Path matching against active working paths
        return any(
            self._path_satisfies_scope(path, rule)
            for path in working_set.active_paths
        )

    def _path_satisfies_scope(self, path: str, rule: RuleItem) -> bool:
        """Check whether a single path matches includes and avoids excludes."""
        normalized_path = path.replace("\\", "/").lstrip("./")

        # Exclude patterns have veto power
        for exc in rule.scope.exclude_patterns:
            norm_exc = exc.replace("\\", "/").lstrip("./")
            if fnmatch.fnmatch(normalized_path, norm_exc):
                return False

        # Include patterns must have at least one match
        for inc in rule.scope.include_patterns:
            norm_inc = inc.replace("\\", "/").lstrip("./")
            if fnmatch.fnmatch(normalized_path, norm_inc):
                return True
            # Also support substring directory match e.g. "tests/*" on "tests/sub/file.py"
            if norm_inc.endswith("/*") and normalized_path.startswith(norm_inc[:-1]):
                return True

        return False

    def _is_universal_rule(self, rule: RuleItem) -> bool:
        """Check if a rule applies universally across all paths."""
        return (
            "*" in rule.scope.include_patterns
            and not rule.scope.exclude_patterns
        )
