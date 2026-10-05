"""Engineering Rule Compiler and Deterministic Preflight Evaluator.

Executes deterministic static assertion checks on design parameter sets against
engineering manufacturing specifications (DRC, clearance, tolerances) without LLM hallucinations.
"""

from collections.abc import Sequence

from .models import (
    EngineeringProceduralRule,
    EngineeringRuleSeverity,
    PreflightCheckReport,
    RuleEvaluationResult,
)


class EngineeringRuleCompilerAndEvaluator:
    """Evaluates design and workflow parameter configurations against procedural engineering constraints."""

    def evaluate_rule(
        self,
        rule: EngineeringProceduralRule,
        value: str | float | int | bool | None,
    ) -> RuleEvaluationResult:
        """Evaluate a single parameter against its corresponding engineering rule.

        Args:
            rule: Target engineering procedural constraint rule.
            value: Parameter value submitted by agent or workflow.

        Returns:
            Structured diagnostic evaluation result.
        """
        if value is None:
            return RuleEvaluationResult(
                rule_id=rule.rule_id,
                parameter_name=rule.parameter_name,
                passed=False,
                severity=rule.severity,
                actual_value=None,
                violation_message=(
                    f"Required engineering parameter '{rule.parameter_name}' "
                    f"is missing from design specification."
                ),
                suggested_value=rule.boundary.min_value,
            )

        boundary = rule.boundary

        # 1. Categorical / Discrete Set Validation
        if boundary.allowed_values is not None:
            val_str = str(value)
            if val_str not in boundary.allowed_values:
                return RuleEvaluationResult(
                    rule_id=rule.rule_id,
                    parameter_name=rule.parameter_name,
                    passed=False,
                    severity=rule.severity,
                    actual_value=value,
                    violation_message=(
                        f"Value '{val_str}' for '{rule.parameter_name}' violates permissible set: "
                        f"{boundary.allowed_values}."
                    ),
                    suggested_value=boundary.allowed_values[0] if boundary.allowed_values else None,
                )

        # 2. Continuous Numeric Bounds Validation
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            num_val = float(value)
            unit_suffix = f" {boundary.unit}" if boundary.unit else ""

            if boundary.min_value is not None and num_val < boundary.min_value:
                return RuleEvaluationResult(
                    rule_id=rule.rule_id,
                    parameter_name=rule.parameter_name,
                    passed=False,
                    severity=rule.severity,
                    actual_value=value,
                    violation_message=(
                        f"Parameter '{rule.parameter_name}' value {num_val}{unit_suffix} "
                        f"is below physical manufacturing threshold {boundary.min_value}{unit_suffix}."
                    ),
                    suggested_value=boundary.min_value,
                )

            if boundary.max_value is not None and num_val > boundary.max_value:
                return RuleEvaluationResult(
                    rule_id=rule.rule_id,
                    parameter_name=rule.parameter_name,
                    passed=False,
                    severity=rule.severity,
                    actual_value=value,
                    violation_message=(
                        f"Parameter '{rule.parameter_name}' value {num_val}{unit_suffix} "
                        f"exceeds maximum manufacturing tolerance {boundary.max_value}{unit_suffix}."
                    ),
                    suggested_value=boundary.max_value,
                )

        return RuleEvaluationResult(
            rule_id=rule.rule_id,
            parameter_name=rule.parameter_name,
            passed=True,
            severity=rule.severity,
            actual_value=value,
            violation_message=None,
            suggested_value=None,
        )

    def evaluate_all(
        self,
        domain: str,
        rules: Sequence[EngineeringProceduralRule],
        parameters: dict[str, str | float | int | bool],
    ) -> PreflightCheckReport:
        """Perform comprehensive preflight evaluation across all activated rules.

        Args:
            domain: Domain name being validated.
            rules: Sequence of active rules to evaluate.
            parameters: Key-value dictionary of design parameters.

        Returns:
            Consolidated PreflightCheckReport detailing pass/fail status and recommended patches.
        """
        violations: list[RuleEvaluationResult] = []
        warnings: list[RuleEvaluationResult] = []
        fixes: dict[str, str | float | int | bool] = {}

        for rule in rules:
            val = parameters.get(rule.parameter_name)
            result = self.evaluate_rule(rule, val)

            if not result.passed:
                if result.severity == EngineeringRuleSeverity.ERROR:
                    violations.append(result)
                elif result.severity == EngineeringRuleSeverity.WARNING:
                    warnings.append(result)

                if result.suggested_value is not None:
                    fixes[rule.parameter_name] = result.suggested_value

        return PreflightCheckReport(
            domain=domain,
            total_rules_checked=len(rules),
            passed=(len(violations) == 0),
            violations=violations,
            warnings=warnings,
            recommended_fixes=fixes,
        )
