"""Hardcoded Python business caps and limits guardrail gate.

[INPUT]
- discount_percent, affected_rows, budget_delta

[OUTPUT]
- BusinessCapsGuardrail: validates numerical bounds and provides compliant alternative suggestions.
- CapsExceededError: raised when business limits are breached.

[POS]
Harness core security module inspired by Anthropic Commerce Agents (Caps & Limits Guardrails Gate).
Enforces hard Python limits that cannot be bypassed via prompt injection.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.provenance_gate.types import (
    CapsExceededError,
    CapsLimitViolation,
)

_DEFAULT_MAX_DISCOUNT_PERCENT: float = 50.0
_DEFAULT_MAX_AFFECTED_ROWS: int = 100
_DEFAULT_MAX_BUDGET_DELTA: float = 1000.0


class BusinessCapsGuardrail:
    """Hardcoded numerical and scope limits enforced directly in Python code."""

    def __init__(
        self,
        max_discount_percent: float = _DEFAULT_MAX_DISCOUNT_PERCENT,
        max_affected_rows: int = _DEFAULT_MAX_AFFECTED_ROWS,
        max_budget_delta: float = _DEFAULT_MAX_BUDGET_DELTA,
    ) -> None:
        self._max_discount_percent = max_discount_percent
        self._max_affected_rows = max_affected_rows
        self._max_budget_delta = max_budget_delta

    @property
    def max_discount_percent(self) -> float:
        """Maximum allowable promotional discount percentage."""
        return self._max_discount_percent

    @property
    def max_affected_rows(self) -> int:
        """Maximum allowable database records mutated in a single call."""
        return self._max_affected_rows

    @property
    def max_budget_delta(self) -> float:
        """Maximum allowable spend delta per transaction."""
        return self._max_budget_delta

    def check_caps(
        self,
        discount_percent: float | None = None,
        affected_rows: int | None = None,
        budget_delta: float | None = None,
    ) -> tuple[CapsLimitViolation, ...]:
        """Validate input metrics against hard caps, returning any violations with safe alternatives."""
        violations: list[CapsLimitViolation] = []

        if discount_percent is not None and discount_percent > self._max_discount_percent:
            violations.append(
                CapsLimitViolation(
                    parameter_name="discount_percent",
                    attempted_value=float(discount_percent),
                    max_allowed_value=self._max_discount_percent,
                    compliant_alternative=self._max_discount_percent,
                    message=(
                        f"Discount rate {discount_percent:.1f}% exceeds hard cap {self._max_discount_percent:.1f}%. "
                        f"Compliant alternative: set discount to {self._max_discount_percent:.1f}%."
                    ),
                )
            )

        if affected_rows is not None and affected_rows > self._max_affected_rows:
            violations.append(
                CapsLimitViolation(
                    parameter_name="affected_rows",
                    attempted_value=float(affected_rows),
                    max_allowed_value=float(self._max_affected_rows),
                    compliant_alternative=float(self._max_affected_rows),
                    message=(
                        f"Mutation scope of {affected_rows} rows exceeds batch cap {self._max_affected_rows}. "
                        f"Compliant alternative: batch in chunks of <= {self._max_affected_rows} rows."
                    ),
                )
            )

        if budget_delta is not None and budget_delta > self._max_budget_delta:
            violations.append(
                CapsLimitViolation(
                    parameter_name="budget_delta",
                    attempted_value=float(budget_delta),
                    max_allowed_value=self._max_budget_delta,
                    compliant_alternative=self._max_budget_delta,
                    message=(
                        f"Budget delta ${budget_delta:.2f} exceeds transaction cap ${self._max_budget_delta:.2f}. "
                        f"Compliant alternative: cap transaction at ${self._max_budget_delta:.2f}."
                    ),
                )
            )

        return tuple(violations)

    def assert_caps(
        self,
        discount_percent: float | None = None,
        affected_rows: int | None = None,
        budget_delta: float | None = None,
    ) -> None:
        """Enforce business caps, raising CapsExceededError with alternatives if breached."""
        violations = self.check_caps(
            discount_percent=discount_percent,
            affected_rows=affected_rows,
            budget_delta=budget_delta,
        )
        if violations:
            raise CapsExceededError(violations=violations)
