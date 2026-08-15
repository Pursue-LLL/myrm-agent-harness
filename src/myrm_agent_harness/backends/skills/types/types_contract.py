"""Structured skill contract types from frontmatter.

[INPUT]
- (none)

[OUTPUT]
- SkillContractTrap, SkillContractVerification, SkillContractJudgment, SkillContract

[POS]
Cache-safe structured contract extracted from skill frontmatter for routing and fallback docs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SkillContractTrap:
    """Structured caution that should survive skill content degradation."""

    description: str
    mitigation: str
    severity: str = "medium"
    trigger_condition: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "description": self.description,
            "mitigation": self.mitigation,
            "severity": self.severity,
        }
        if self.trigger_condition:
            payload["trigger_condition"] = self.trigger_condition
        return payload


@dataclass(frozen=True, slots=True)
class SkillContractVerification:
    """Structured verification step for confirming skill success."""

    step_id: str
    description: str
    validation_method: str
    expected_output: str | None = None
    is_required: bool = True

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "step_id": self.step_id,
            "description": self.description,
            "validation_method": self.validation_method,
            "is_required": self.is_required,
        }
        if self.expected_output:
            payload["expected_output"] = self.expected_output
        return payload


@dataclass(frozen=True, slots=True)
class SkillContractJudgment:
    """Structured branch point that the model should reason about explicitly."""

    judgment_id: str
    description: str
    condition: str
    true_branch: str
    false_branch: str
    rationale: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "judgment_id": self.judgment_id,
            "description": self.description,
            "condition": self.condition,
            "true_branch": self.true_branch,
            "false_branch": self.false_branch,
        }
        if self.rationale:
            payload["rationale"] = self.rationale
        return payload


@dataclass(frozen=True, slots=True)
class SkillContract:
    """Cache-safe structured contract extracted from skill frontmatter."""

    steps: tuple[str, ...] = ()
    key_judgments: tuple[SkillContractJudgment, ...] = ()
    potential_traps: tuple[SkillContractTrap, ...] = ()
    verification_steps: tuple[SkillContractVerification, ...] = ()
    dependencies: tuple[str, ...] = ()
    estimated_duration_seconds: float | None = None
    success_criteria: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "steps": list(self.steps),
            "key_judgments": [judgment.to_dict() for judgment in self.key_judgments],
            "potential_traps": [trap.to_dict() for trap in self.potential_traps],
            "verification_steps": [step.to_dict() for step in self.verification_steps],
            "dependencies": list(self.dependencies),
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "success_criteria": self.success_criteria,
        }
