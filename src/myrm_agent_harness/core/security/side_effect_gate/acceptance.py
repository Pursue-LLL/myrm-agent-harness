"""Deterministic post-run acceptance evaluator for Agent deliverables.

[INPUT]
- Text content or structured dictionary deliverables, list of deterministic AcceptanceRule

[OUTPUT]
- AcceptanceReport: Verification verdict with detailed violations

[POS]
Harness post-run delivery assurance. Separates completion from acceptance by enforcing
purely deterministic, uncheatable assertions (length, structure, non-empty, arithmetic balance)
prior to final task handover or customer notification.
"""

from __future__ import annotations

import math

from myrm_agent_harness.core.security.side_effect_gate.types import (
    AcceptanceReport,
    AcceptanceRule,
    AcceptanceRuleType,
    AcceptanceViolation,
)

type StructuredDataValue = (
    str
    | int
    | float
    | bool
    | None
    | list[str]
    | list[int]
    | list[float]
    | list[dict[str, float | int | str]]
    | dict[str, str | int | float | bool | None]
)
type StructuredDeliverable = dict[str, StructuredDataValue]


class DeterministicAcceptanceEvaluator:
    """Evaluates agent output deliverables against deterministic quality rules."""

    def evaluate_text(self, content: str, rules: list[AcceptanceRule]) -> AcceptanceReport:
        """Run deterministic quality checks against free-form text or markdown deliverable."""
        violations: list[AcceptanceViolation] = []
        trimmed = content.strip()

        for rule in rules:
            match rule.rule_type:
                case AcceptanceRuleType.NON_EMPTY:
                    if not trimmed:
                        violations.append(
                            AcceptanceViolation(
                                rule_type=rule.rule_type,
                                message="Deliverable content is empty or contains only whitespace",
                                actual_value="",
                            )
                        )
                case AcceptanceRuleType.LENGTH_BOUNDS:
                    length = len(trimmed)
                    if rule.min_length is not None and length < rule.min_length:
                        violations.append(
                            AcceptanceViolation(
                                rule_type=rule.rule_type,
                                message=f"Content length {length} is below required minimum of {rule.min_length}",
                                actual_value=length,
                            )
                        )
                    if rule.max_length is not None and length > rule.max_length:
                        violations.append(
                            AcceptanceViolation(
                                rule_type=rule.rule_type,
                                message=f"Content length {length} exceeds allowed maximum of {rule.max_length}",
                                actual_value=length,
                            )
                        )
                case AcceptanceRuleType.REQUIRED_STRUCTURE:
                    if rule.required_sections:
                        for section in rule.required_sections:
                            if section not in content:
                                violations.append(
                                    AcceptanceViolation(
                                        rule_type=rule.rule_type,
                                        message=f"Missing required structure section: '{section}'",
                                        actual_value=section,
                                    )
                                )
                case _:
                    pass

        passed = len(violations) == 0
        summary = (
            "All deterministic acceptance checks passed successfully"
            if passed
            else f"Acceptance failed with {len(violations)} rule violations"
        )
        return AcceptanceReport(passed=passed, violations=violations, summary=summary)

    def evaluate_structured(
        self,
        payload: StructuredDeliverable,
        rules: list[AcceptanceRule],
    ) -> AcceptanceReport:
        """Run deterministic quality checks against structured dictionary deliverables."""
        violations: list[AcceptanceViolation] = []

        for rule in rules:
            match rule.rule_type:
                case AcceptanceRuleType.NON_EMPTY:
                    if not payload:
                        violations.append(
                            AcceptanceViolation(
                                rule_type=rule.rule_type,
                                message="Structured deliverable payload is empty",
                                actual_value=0,
                            )
                        )
                case AcceptanceRuleType.REQUIRED_JSON_KEYS:
                    if rule.required_json_keys:
                        for key in rule.required_json_keys:
                            if key not in payload:
                                violations.append(
                                    AcceptanceViolation(
                                        rule_type=rule.rule_type,
                                        message=f"Required top-level key missing from deliverable: '{key}'",
                                        actual_value=key,
                                    )
                                )
                case AcceptanceRuleType.NUMERICAL_SUM_EQUALS:
                    self._check_numerical_sum(payload, rule, violations)
                case _:
                    pass

        passed = len(violations) == 0
        summary = (
            "Structured deliverable passed all deterministic acceptance rules"
            if passed
            else f"Structured deliverable failed with {len(violations)} violations"
        )
        return AcceptanceReport(passed=passed, violations=violations, summary=summary)

    def _check_numerical_sum(
        self,
        payload: StructuredDeliverable,
        rule: AcceptanceRule,
        violations: list[AcceptanceViolation],
    ) -> None:
        """Verify that itemized values sum precisely to the declared total."""
        if not rule.total_field_name or rule.total_field_name not in payload:
            violations.append(
                AcceptanceViolation(
                    rule_type=rule.rule_type,
                    message=f"Total field '{rule.total_field_name}' not found in deliverable",
                    actual_value=None,
                )
            )
            return

        raw_total = payload[rule.total_field_name]
        if not isinstance(raw_total, (int, float)):
            violations.append(
                AcceptanceViolation(
                    rule_type=rule.rule_type,
                    message=f"Total field '{rule.total_field_name}' is not numeric",
                    actual_value=str(raw_total),
                )
            )
            return

        expected_total = float(raw_total)
        calculated_sum = 0.0

        if rule.sum_field_names:
            for field_name in rule.sum_field_names:
                val = payload.get(field_name)
                if isinstance(val, (int, float)):
                    calculated_sum += float(val)
                elif isinstance(val, list):
                    for elem in val:
                        if isinstance(elem, (int, float)):
                            calculated_sum += float(elem)
                        elif isinstance(elem, dict) and "amount" in elem:
                            amt = elem["amount"]
                            if isinstance(amt, (int, float)):
                                calculated_sum += float(amt)
                else:
                    violations.append(
                        AcceptanceViolation(
                            rule_type=rule.rule_type,
                            message=f"Sum constituent field '{field_name}' is non-numeric or missing",
                            actual_value=str(val),
                        )
                    )

        if not math.isclose(calculated_sum, expected_total, rel_tol=1e-5, abs_tol=1e-4):
            violations.append(
                AcceptanceViolation(
                    rule_type=rule.rule_type,
                    message=(
                        f"Numerical consistency violation: calculated sum {calculated_sum:.2f} "
                        f"does not equal declared total {expected_total:.2f}"
                    ),
                    actual_value=calculated_sum,
                )
            )
