"""Tests for SkillQualityLinter static audit based on 7 Golden Rules."""

from __future__ import annotations

from myrm_agent_harness.backends.skills.scanning.quality_linter import (
    QualityRuleId,
    SkillQualityLinter,
)

SAMPLE_PERFECT_SKILL = """---
name: code-refactoring-expert
description: Specialized skill for automated high-performance code refactoring, complexity reduction, and architectural cleanup.
version: 1.0.0
---

# Instructions

Execute codebase analysis and extract complex methods.
Do not use for general database migrations; use the db-migration skill instead.

## Output Format

```json
{
  "refactored_files": ["example.py"],
  "status": "success"
}
```

## Example

### Example Input
Analyze function `process_data`.

### Example Output
Extracted helper functions and reduced cyclomatic complexity.
"""

SAMPLE_POOR_SKILL = """---
name: bad-skill
description: Too short
---

Please could you help us check this code?
"""


def test_skill_quality_linter_perfect_score() -> None:
    report = SkillQualityLinter.lint_content(SAMPLE_PERFECT_SKILL)
    assert report.is_passed is True
    assert report.score >= 85
    assert len(report.violations) == 0 or all(v.penalty <= 10 for v in report.violations)


def test_skill_quality_linter_catches_violations() -> None:
    report = SkillQualityLinter.lint_content(SAMPLE_POOR_SKILL)
    assert report.is_passed is False
    assert report.score < 70

    rule_ids = {v.rule_id for v in report.violations}
    assert QualityRuleId.DESCRIPTION_ROUTING in rule_ids
    assert QualityRuleId.NEGATIVE_BOUNDARY in rule_ids
    assert QualityRuleId.IMPERATIVE_COMMANDS in rule_ids
    assert QualityRuleId.OUTPUT_TEMPLATE in rule_ids
    assert QualityRuleId.WORKED_EXAMPLES in rule_ids

    d = report.to_dict()
    assert "score" in d
    assert "violations" in d
    assert isinstance(d["suggestions"], list)
