# [INPUT]: RuleFileDescriptor
# [OUTPUT]: parse_rule_frontmatter, is_rule_active_for_targets, match_rules_against_targets
# [POS]: agent/context_management/hierarchical_rules/glob_rule_matcher.py

"""Glob-scoped dynamic rule matcher evaluating path activation criteria.

[INPUT]
- RuleFileDescriptor: Parsed rule document model.

[OUTPUT]
- parse_rule_frontmatter: Extracts YAML-style frontmatter headers specifying paths.
- is_rule_active_for_targets: Evaluates whether active workspace target paths trigger rule scoping.
- match_rules_against_targets: Filters full rule inventory into active and suppressed sets.

[POS]
Pattern-matching engine suppressing non-pertinent domain rules to prevent token waste and conflicts.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Sequence

from .rule_types import RuleFileDescriptor

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
PATHS_LINE_PATTERN = re.compile(r"paths:\s*\[(.*?)\]", re.IGNORECASE)


def parse_rule_frontmatter(content: str) -> tuple[list[str], str]:
    """Parse frontmatter header extracting path globs and returning stripped body.

    Supports simple inline list syntax:
    ---
    paths: ["src/billing/**", "app/services/commerce/**"]
    ---
    """
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return [], content

    fm_raw = match.group(1)
    body = content[match.end() :]

    globs: list[str] = []
    # Match paths: ["glob1", "glob2"]
    paths_match = PATHS_LINE_PATTERN.search(fm_raw)
    if paths_match:
        items = paths_match.group(1).split(",")
        for it in items:
            cleaned = it.strip().strip("\"'").strip()
            if cleaned:
                globs.append(cleaned)
    else:
        # Fallback multi-line list matching: - "pattern"
        for line in fm_raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                cleaned_val = stripped[2:].strip().strip("\"'").strip()
                if cleaned_val:
                    globs.append(cleaned_val)

    return globs, body


def is_rule_active_for_targets(
    glob_patterns: Sequence[str],
    target_files: Sequence[str],
) -> bool:
    """Determine whether rule is triggered given current target file paths.

    If glob_patterns is empty, the rule is global and ALWAYS active.
    If glob_patterns is non-empty and target_files is empty, the rule is suppressed.
    If at least one target file satisfies at least one glob pattern, rule is active.
    """
    if not glob_patterns:
        return True

    if not target_files:
        return False

    for target in target_files:
        normalized_target = target.replace("\\", "/").lstrip("./")
        for pattern in glob_patterns:
            normalized_pattern = pattern.replace("\\", "/").lstrip("./")
            # Exact match or glob match
            if fnmatch.fnmatch(normalized_target, normalized_pattern):
                return True
            # Support directory recursive wildcards like src/** matching src/sub/file.py
            if normalized_pattern.endswith("/**"):
                dir_prefix = normalized_pattern[:-3]
                if normalized_target.startswith(dir_prefix):
                    return True

    return False


def match_rules_against_targets(
    rules: Sequence[RuleFileDescriptor],
    target_files: Sequence[str],
) -> tuple[list[RuleFileDescriptor], list[RuleFileDescriptor]]:
    """Partition rules into active and suppressed subsets according to target files."""
    active: list[RuleFileDescriptor] = []
    suppressed: list[RuleFileDescriptor] = []

    for rule in rules:
        if is_rule_active_for_targets(rule.glob_patterns, target_files):
            active.append(rule)
        else:
            suppressed.append(rule)

    return active, suppressed
