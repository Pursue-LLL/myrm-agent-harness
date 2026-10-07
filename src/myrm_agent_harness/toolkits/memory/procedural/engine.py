"""Domain Engineering Procedural Memory and Skill Workflow Engine.

Manages versioned engineering rules, context-driven progressive disclosure,
deterministic preflight gate assertions, and automated parameter remediation.

[INPUT]
- toolkits.memory.procedural.evaluator::EngineeringRuleCompilerAndEvaluator (POS: Engineering Rule Compiler
  and Deterministic Preflight Evaluator.)
- toolkits.memory.procedural.models::EngineeringProceduralRule, PreflightCheckReport (POS: Data models for
  User Intervention to Procedural Memory Distillation Engine.)

[OUTPUT]
- EngineeringPreflightViolationError: Raised when design parameters violate blocking engineering constraints
  during preflight checks.
- DomainEngineeringProceduralEngine: Orchestrates procedural engineering specifications, rule versioning,
  and validation gates.

[POS]
Domain Engineering Procedural Memory and Skill Workflow Engine.
"""

from collections.abc import Sequence

from .evaluator import EngineeringRuleCompilerAndEvaluator
from .models import (
    EngineeringProceduralRule,
    PreflightCheckReport,
)


class EngineeringPreflightViolationError(RuntimeError):
    """Raised when design parameters violate blocking engineering constraints during preflight checks."""

    def __init__(self, report: PreflightCheckReport) -> None:
        """Initialize error with comprehensive preflight report.

        Args:
            report: Detailed violation report detailing failing constraints.
        """
        error_msgs = [
            f"[{v.rule_id}] {v.violation_message}" for v in report.violations
        ]
        summary = "; ".join(error_msgs)
        super().__init__(
            f"Preflight DRC / Engineering gate blocked {len(report.violations)} "
            f"violations in domain '{report.domain}': {summary}"
        )
        self.report = report


class DomainEngineeringProceduralEngine:
    """Orchestrates procedural engineering specifications, rule versioning, and validation gates."""

    def __init__(
        self,
        evaluator: EngineeringRuleCompilerAndEvaluator | None = None,
    ) -> None:
        """Initialize procedural engine with evaluator and versioned rule repositories."""
        self._evaluator = evaluator or EngineeringRuleCompilerAndEvaluator()
        # Mapping: rule_id -> {version_str -> EngineeringProceduralRule}
        self._rule_registry: dict[str, dict[str, EngineeringProceduralRule]] = {}
        # Mapping: rule_id -> active_version_str
        self._active_versions: dict[str, str] = {}

    @property
    def total_registered_rules(self) -> int:
        """Return count of unique active procedural rules."""
        return len(self._active_versions)

    def register_rule(
        self,
        rule: EngineeringProceduralRule,
        activate: bool = True,
    ) -> None:
        """Register a versioned engineering procedural rule into memory.

        Args:
            rule: Engineering procedural rule specification.
            activate: Whether to immediately activate this version as current.
        """
        if rule.rule_id not in self._rule_registry:
            self._rule_registry[rule.rule_id] = {}

        self._rule_registry[rule.rule_id][rule.version] = rule

        if activate or rule.rule_id not in self._active_versions:
            self._active_versions[rule.rule_id] = rule.version

    def register_rules(
        self,
        rules: Sequence[EngineeringProceduralRule],
        activate: bool = True,
    ) -> int:
        """Batch register multiple procedural rules."""
        for r in rules:
            self.register_rule(r, activate=activate)
        return len(rules)

    def switch_rule_version(self, rule_id: str, target_version: str) -> None:
        """Switch or rollback active version of a procedural rule.

        Args:
            rule_id: Rule identifier to switch.
            target_version: Desired version string.

        Raises:
            KeyError: If rule or version does not exist.
        """
        if rule_id not in self._rule_registry:
            raise KeyError(f"Rule '{rule_id}' is not registered.")
        if target_version not in self._rule_registry[rule_id]:
            raise KeyError(
                f"Version '{target_version}' for rule '{rule_id}' does not exist. "
                f"Available: {list(self._rule_registry[rule_id].keys())}"
            )
        self._active_versions[rule_id] = target_version

    def get_active_rule(self, rule_id: str) -> EngineeringProceduralRule | None:
        """Retrieve the currently active specification for a rule."""
        active_ver = self._active_versions.get(rule_id)
        if not active_ver:
            return None
        return self._rule_registry.get(rule_id, {}).get(active_ver)

    def assemble_rules_for_context(
        self,
        domain: str,
        active_tags: Sequence[str] | None = None,
    ) -> list[EngineeringProceduralRule]:
        """Assemble relevant rules via progressive disclosure based on domain and context tags.

        Args:
            domain: Target engineering domain (e.g., 'pcb_drc').
            active_tags: Contextual tags characterizing the active workflow/subtask.

        Returns:
            List of matching active procedural rules.
        """
        tag_set = {t.lower().strip() for t in (active_tags or [])}
        matched_rules: list[EngineeringProceduralRule] = []

        for rule_id, ver in self._active_versions.items():
            rule = self._rule_registry[rule_id][ver]
            if rule.domain.lower() != domain.lower():
                continue

            # If rule has precondition tags, all must be present in context
            if rule.precondition_tags:
                required = {pt.lower().strip() for pt in rule.precondition_tags}
                if not required.issubset(tag_set):
                    continue

            matched_rules.append(rule)

        return matched_rules

    def preflight_check(
        self,
        domain: str,
        parameters: dict[str, str | float | int | bool],
        active_tags: Sequence[str] | None = None,
    ) -> PreflightCheckReport:
        """Execute non-throwing preflight verification against active procedural constraints.

        Args:
            domain: Target engineering domain.
            parameters: Submitted design parameters.
            active_tags: Context tags for progressive disclosure.

        Returns:
            Detailed PreflightCheckReport.
        """
        rules = self.assemble_rules_for_context(domain, active_tags)
        return self._evaluator.evaluate_all(domain, rules, parameters)

    def enforce_preflight_gate(
        self,
        domain: str,
        parameters: dict[str, str | float | int | bool],
        active_tags: Sequence[str] | None = None,
    ) -> PreflightCheckReport:
        """Enforce strict preflight gate; raises exception if blocking errors are detected.

        Args:
            domain: Target engineering domain.
            parameters: Submitted design parameters.
            active_tags: Context tags for progressive disclosure.

        Returns:
            PreflightCheckReport when verification passes.

        Raises:
            EngineeringPreflightViolationError: When any blocking rule is violated.
        """
        report = self.preflight_check(domain, parameters, active_tags)
        if not report.passed:
            raise EngineeringPreflightViolationError(report)
        return report

    def auto_remediate_parameters(
        self,
        domain: str,
        parameters: dict[str, str | float | int | bool],
        active_tags: Sequence[str] | None = None,
    ) -> dict[str, str | float | int | bool]:
        """Apply recommended parameter patches to produce compliant engineering parameters.

        Args:
            domain: Target engineering domain.
            parameters: Input design parameters.
            active_tags: Context tags for progressive disclosure.

        Returns:
            A new parameter dictionary with fixes applied.
        """
        report = self.preflight_check(domain, parameters, active_tags)
        remediated = dict(parameters)
        remediated.update(report.recommended_fixes)
        return remediated
