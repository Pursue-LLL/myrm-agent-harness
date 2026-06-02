"""Skill evolution validation system.

Ensures evolved skills are safe and functional before deployment.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord (POS: Data types for skill evolution system.)

[OUTPUT]
- ValidationResult: Validation result.
- SkillValidator: Validates evolved skills for safety and correctness.

[POS]
Skill evolution validation system.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass

from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord

logger = logging.getLogger(__name__)

__all__ = ["SkillValidator", "ValidationResult"]


@dataclass
class ValidationResult:
    """Result of skill validation."""

    valid: bool
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return self.valid and not self.errors


class SkillValidator:
    """Validates evolved skills for safety and correctness."""

    def __init__(self):
        """Initialize validator."""
        self._dangerous_patterns = [
            r"rm\s+-rf",
            r"sudo\s+",
            r"eval\(",
            r"exec\(",
            r"__import__",
        ]

    def validate(self, skill: SkillRecord) -> ValidationResult:
        """Validate evolved skill.

        Checks:
        1. Syntax validity (for code blocks)
        2. Security (no dangerous patterns)
        3. Basic structure (has required fields)

        Args:
            skill: SkillRecord to validate

        Returns:
            ValidationResult with errors/warnings
        """
        errors = []
        warnings = []

        # Check basic structure
        if not skill.name or not skill.content:
            errors.append("Skill missing name or content")

        # Check for dangerous patterns
        for pattern in self._dangerous_patterns:
            if re.search(pattern, skill.content, re.IGNORECASE):
                errors.append(f"Dangerous pattern detected: {pattern}")

        # Validate Python code blocks
        code_blocks = self._extract_code_blocks(skill.content, "python")
        for i, code in enumerate(code_blocks, 1):
            try:
                ast.parse(code)
            except SyntaxError as e:
                errors.append(f"Python syntax error in block {i}: {e}")

        # Check skill metadata
        if skill.lineage and skill.lineage.change_summary == "":
            warnings.append("Empty change summary")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def _extract_code_blocks(self, content: str, language: str) -> list[str]:
        """Extract code blocks from markdown content."""
        pattern = rf"```{language}\n(.*?)\n```"
        matches = re.findall(pattern, content, re.DOTALL)
        return matches
