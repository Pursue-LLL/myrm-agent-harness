"""ACI (Agent-Computer Interface) tool contract and Goldilocks Zone prompt linter.

Ensures zero-overlap tool designs, well-scoped parameter contracts, and
strict adherence to XML partitioned Goldilocks Zone system prompt principles.

[INPUT]
- runtime.context.context_engineering_types::ACILintIssue, ACILintReport, ACISeverity, ACIToolContract (POS:
  Context engineering types and data protocols for ReAct trap remediation and ACI design.)

[OUTPUT]
- ACIToolContractLinter: Static analyzer for ACI tool contracts and Goldilocks Zone prompts.

[POS]
ACI (Agent-Computer Interface) tool contract and Goldilocks Zone prompt linter.
"""

from __future__ import annotations

import re
from typing import ClassVar

from myrm_agent_harness.runtime.context.context_engineering_types import (
    ACILintIssue,
    ACILintReport,
    ACISeverity,
    ACIToolContract,
)


class ACIToolContractLinter:
    """Static analyzer for ACI tool contracts and Goldilocks Zone prompts."""

    VAGUE_NAMES: ClassVar[set[str]] = {
        "process",
        "do_stuff",
        "run",
        "execute",
        "handle",
        "helper",
        "action",
        "custom",
    }

    REQUIRED_PROMPT_TAGS: ClassVar[list[str]] = [
        "role",
        "principles",
        "boundaries",
        "tools_guidance",
    ]

    def lint_tools(self, tools: list[ACIToolContract]) -> ACILintReport:
        """Run comprehensive ACI quality checks on a catalog of tools."""
        issues: list[ACILintIssue] = []

        # 1. Individual tool checks
        for tool in tools:
            # Check name specificity
            name_lower = tool.name.lower()
            if name_lower in self.VAGUE_NAMES or len(tool.name) < 3:
                issues.append(
                    ACILintIssue(
                        severity=ACISeverity.ERROR,
                        rule_code="ACI_TOOL_NAME_TOO_VAGUE",
                        target_name=tool.name,
                        message=f"Tool name '{tool.name}' is too vague. Use descriptive verb_noun naming.",
                    )
                )

            # Check description length and clarity
            if len(tool.description.strip()) < 20:
                issues.append(
                    ACILintIssue(
                        severity=ACISeverity.WARNING,
                        rule_code="ACI_TOOL_DESC_TOO_BRIEF",
                        target_name=tool.name,
                        message=f"Tool '{tool.name}' description is under 20 characters; risks model confusion.",
                    )
                )

            # Check parameter definitions
            for param in tool.parameters:
                if param.type_str.lower() in ("any", "unknown"):
                    issues.append(
                        ACILintIssue(
                            severity=ACISeverity.ERROR,
                            rule_code="ACI_PARAM_ANY_TYPE_PROHIBITED",
                            target_name=f"{tool.name}.{param.name}",
                            message=f"Parameter '{param.name}' specifies forbidden '{param.type_str}' type.",
                        )
                    )
                if len(param.description.strip()) < 5:
                    issues.append(
                        ACILintIssue(
                            severity=ACISeverity.WARNING,
                            rule_code="ACI_PARAM_DESC_MISSING",
                            target_name=f"{tool.name}.{param.name}",
                            message=f"Parameter '{param.name}' lacks descriptive documentation.",
                        )
                    )

        # 2. Cross-tool semantic overlap check
        n = len(tools)
        for i in range(n):
            for j in range(i + 1, n):
                t1, t2 = tools[i], tools[j]
                overlap_ratio = self._calculate_word_jaccard(
                    t1.description, t2.description
                )
                if overlap_ratio > 0.65:
                    issues.append(
                        ACILintIssue(
                            severity=ACISeverity.WARNING,
                            rule_code="ACI_TOOL_SEMANTIC_OVERLAP",
                            target_name=f"{t1.name} <-> {t2.name}",
                            message=(
                                f"Tools '{t1.name}' and '{t2.name}' share high semantic overlap "
                                f"({overlap_ratio:.2f}); risk of decision paralysis."
                            ),
                        )
                    )

        has_errors = any(issue.severity == ACISeverity.ERROR for issue in issues)
        return ACILintReport(passed=not has_errors, issues=issues)

    def lint_goldilocks_prompt(self, system_prompt: str) -> ACILintReport:
        """Validate Goldilocks Zone XML partition structure and sizing bounds."""
        issues: list[ACILintIssue] = []

        # Verify XML partition tags
        for tag in self.REQUIRED_PROMPT_TAGS:
            open_tag = f"<{tag}>"
            close_tag = f"</{tag}>"
            if open_tag not in system_prompt or close_tag not in system_prompt:
                issues.append(
                    ACILintIssue(
                        severity=ACISeverity.ERROR,
                        rule_code="GOLDILOCKS_MISSING_XML_PARTITION",
                        target_name=tag,
                        message=f"System prompt missing required Goldilocks partition: <{tag}>...</{tag}>.",
                    )
                )

        # Check prompt volume bounds (Goldilocks: neither too sparse nor excessively bloated)
        words = system_prompt.split()
        word_count = len(words)

        if word_count < 30:
            issues.append(
                ACILintIssue(
                    severity=ACISeverity.ERROR,
                    rule_code="GOLDILOCKS_UNDER_SPECIFIED",
                    target_name="system_prompt",
                    message="System prompt is under 30 words; insufficient constraints.",
                )
            )
        elif word_count > 2500:
            issues.append(
                ACILintIssue(
                    severity=ACISeverity.WARNING,
                    rule_code="GOLDILOCKS_OVER_SPECIFIED_BLOAT",
                    target_name="system_prompt",
                    message=(
                        f"System prompt is {word_count} words; excessive rule enumerations "
                        f"lead to brittle compliance and rule decay."
                    ),
                )
            )

        has_errors = any(issue.severity == ACISeverity.ERROR for issue in issues)
        return ACILintReport(passed=not has_errors, issues=issues)

    def _calculate_word_jaccard(self, text_a: str, text_b: str) -> float:
        """Calculate word-level Jaccard similarity coefficient."""
        words_a = set(re.findall(r"\b[a-zA-Z_]{3,}\b", text_a.lower()))
        words_b = set(re.findall(r"\b[a-zA-Z_]{3,}\b", text_b.lower()))

        if not words_a or not words_b:
            return 0.0

        intersection = words_a.intersection(words_b)
        union = words_a.union(words_b)

        return len(intersection) / len(union)
