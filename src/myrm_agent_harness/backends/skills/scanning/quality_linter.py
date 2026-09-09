"""Skill Quality Linter based on 7 Golden Rules.

Provides static specification auditing, negative routing boundary checking,
imperative instruction scoring, output template validation, depth & brevity analysis,
and actionable remediation suggestion generation.

[INPUT]
- backends.skills._utils::parse_frontmatter (POS: SKILL.md frontmatter parser)

[OUTPUT]
- SkillQualityViolation: Single rule violation record
- SkillQualityReport: Comprehensive quality score (0-100) and suggestions
- SkillQualityLinter: Static analysis engine for SKILL.md contents

[POS]
myrm-agent-harness/src/myrm_agent_harness/backends/skills/scanning/quality_linter.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import logging
import re

from myrm_agent_harness.backends.skills._utils import parse_frontmatter

logger = logging.getLogger(__name__)

# Action verbs commonly used for imperative commands
IMPERATIVE_VERBS: frozenset[str] = frozenset({
    "run", "execute", "check", "verify", "fetch", "get", "set", "create",
    "delete", "update", "build", "parse", "extract", "validate", "generate",
    "inspect", "query", "call", "send", "receive", "load", "save", "scan",
    "clean", "filter", "sort", "format", "render", "return", "ensure",
})

POLITE_REQUEST_PREFIXES: tuple[str, ...] = (
    "please", "could you", "would you", "kindly", "you should", "we need you to",
)


class QualityRuleId(StrEnum):
    DESCRIPTION_ROUTING = "Q101_DESCRIPTION_ROUTING"
    NEGATIVE_BOUNDARY = "Q102_NEGATIVE_BOUNDARY"
    IMPERATIVE_COMMANDS = "Q103_IMPERATIVE_COMMANDS"
    OUTPUT_TEMPLATE = "Q104_OUTPUT_TEMPLATE"
    WORKED_EXAMPLES = "Q105_WORKED_EXAMPLES"
    ONE_LEVEL_DEEP = "Q106_ONE_LEVEL_DEEP"
    SCRIPT_OFFLOADING = "Q107_SCRIPT_OFFLOADING"


@dataclass(frozen=True, slots=True)
class SkillQualityViolation:
    rule_id: QualityRuleId
    rule_name: str
    message: str
    penalty: int
    suggestion: str


@dataclass(frozen=True, slots=True)
class SkillQualityReport:
    score: int  # 0 to 100
    is_passed: bool  # True if score >= 70
    violations: list[SkillQualityViolation] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "is_passed": self.is_passed,
            "violations": [
                {
                    "rule_id": v.rule_id.value,
                    "rule_name": v.rule_name,
                    "message": v.message,
                    "penalty": v.penalty,
                    "suggestion": v.suggestion,
                }
                for v in self.violations
            ],
            "suggestions": self.suggestions,
        }


class SkillQualityLinter:
    """Static linter for auditing SKILL.md against the 7 Golden Rules."""

    @classmethod
    def lint_content(cls, content: str) -> SkillQualityReport:
        frontmatter, body = parse_frontmatter(content)
        violations: list[SkillQualityViolation] = []

        description = str(frontmatter.get("description", "")).strip()
        name = str(frontmatter.get("name", "")).strip()

        # Rule 1: Description is the routing layer (>= 60 chars, rich context)
        if len(description) < 60:
            violations.append(
                SkillQualityViolation(
                    rule_id=QualityRuleId.DESCRIPTION_ROUTING,
                    rule_name="Routing Description Depth",
                    message=f"Description is too short ({len(description)} chars). Aim for at least 60 chars with clear intent keywords.",
                    penalty=25,
                    suggestion="Expand description with specific trigger keywords, user intent scenarios, and core capabilities.",
                )
            )

        # Rule 2: Negative Routing Boundary (Do not use for X, use /Y instead)
        body_lower = body.lower()
        has_negative_boundary = any(
            phrase in body_lower or phrase in description.lower()
            for phrase in (
                "do not use for", "don't use for", "not for", "avoid using for",
                "use /", "use `", "when not to use",
            )
        )
        if not has_negative_boundary:
            violations.append(
                SkillQualityViolation(
                    rule_id=QualityRuleId.NEGATIVE_BOUNDARY,
                    rule_name="Negative Routing Boundary",
                    message="Missing explicit negative routing boundary to prevent intent overlap.",
                    penalty=15,
                    suggestion="Add a 'When NOT to use' or 'Do not use for X, use Y instead' boundary section.",
                )
            )

        # Rule 3: Imperative Commands vs Polite Requests
        lines = [line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")]
        polite_count = 0
        for line in lines:
            line_lower = line.lower()
            if any(line_lower.startswith(p) for p in POLITE_REQUEST_PREFIXES):
                polite_count += 1

        if polite_count > 0:
            violations.append(
                SkillQualityViolation(
                    rule_id=QualityRuleId.IMPERATIVE_COMMANDS,
                    rule_name="Imperative Instruction Style",
                    message=f"Detected {polite_count} polite request phrasing(s). Skills must use concise, authoritative imperative verbs.",
                    penalty=15,
                    suggestion="Replace phrases like 'Please check...' with direct commands like 'Check...', 'Verify...', 'Execute...'.",
                )
            )

        # Rule 4: Output Template Anchor
        has_template = any(
            marker in body for marker in ("```markdown", "```json", "### Output Template", "## Output Format", "<output_template>")
        ) or ("```" in body and "template" in body_lower)

        if not has_template:
            violations.append(
                SkillQualityViolation(
                    rule_id=QualityRuleId.OUTPUT_TEMPLATE,
                    rule_name="Deterministic Output Template",
                    message="Missing structured output template. Without an explicit format, models invent unstable layouts.",
                    penalty=20,
                    suggestion="Add an explicit markdown or JSON output code block template under an '## Output Format' section.",
                )
            )

        # Rule 5: Worked Example
        has_example = any(
            marker in body_lower for marker in ("## example", "### example", "<example>", "example input", "example output")
        )
        if not has_example:
            violations.append(
                SkillQualityViolation(
                    rule_id=QualityRuleId.WORKED_EXAMPLES,
                    rule_name="Concrete Worked Example",
                    message="Missing concrete end-to-end worked example.",
                    penalty=15,
                    suggestion="Include at least one complete input/output example showing exact behavior.",
                )
            )

        # Rule 6: One-Level Deep Reference Rule
        nested_refs = re.findall(r"(\.\./|\./|/)([\w\-]+/){3,}", body)
        if len(nested_refs) > 0:
            violations.append(
                SkillQualityViolation(
                    rule_id=QualityRuleId.ONE_LEVEL_DEEP,
                    rule_name="One Level Deep Hierarchy",
                    message="Detected deep directory traversal or reference chaining. Keep references strictly 1-level deep.",
                    penalty=10,
                    suggestion="Flatten referenced auxiliary files into the same root directory or single subfolder.",
                )
            )

        # Compute final score
        total_penalty = sum(v.penalty for v in violations)
        score = max(0, 100 - total_penalty)
        suggestions = [v.suggestion for v in violations]

        return SkillQualityReport(
            score=score,
            is_passed=score >= 70,
            violations=violations,
            suggestions=suggestions,
        )
