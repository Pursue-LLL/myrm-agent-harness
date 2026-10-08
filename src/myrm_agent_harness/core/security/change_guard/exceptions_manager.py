"""File-backed exception management for ChangeGuard.

[INPUT]
- ChangeGuardException definitions and live findings.

[OUTPUT]
- Exemption verdicts, expiration tracking, and staleness detection.

[POS]
- Core exception verification logic enforcing WS4 audit standards.
"""

from __future__ import annotations

import fnmatch
import logging

from .types import ChangeGuardException, HardenedFinding

logger = logging.getLogger(__name__)


class ChangeGuardExceptionsManager:
    """Manages file-backed exceptions, ensuring no silent or expired exemptions exist."""

    def __init__(self, exceptions: tuple[ChangeGuardException, ...] = ()) -> None:
        self._exceptions: list[ChangeGuardException] = list(exceptions)

    @property
    def exceptions(self) -> tuple[ChangeGuardException, ...]:
        """Return tuple of all registered exceptions."""
        return tuple(self._exceptions)

    def add_exception(self, exception: ChangeGuardException) -> None:
        """Register a new exception record."""
        self._exceptions.append(exception)

    def is_match(self, exc: ChangeGuardException, finding: HardenedFinding) -> bool:
        """Evaluate if an exception matches a finding by ID/rule and target scope."""
        rule_or_id_match = (
            exc.finding_or_rule_id == finding.finding_id
            or exc.finding_or_rule_id == finding.rule_id
            or exc.finding_or_rule_id == "*"
        )
        if not rule_or_id_match:
            return False

        if exc.scope == "*" or exc.scope == finding.target_object:
            return True

        # Support wildcard scope patterns, e.g. "tools/*" or "prompts/*.md"
        return fnmatch.fnmatch(finding.target_object, exc.scope)

    def evaluate_findings(
        self,
        findings: tuple[HardenedFinding, ...],
        current_time_iso: str,
    ) -> tuple[tuple[HardenedFinding, ...], tuple[str, ...], tuple[str, ...]]:
        """Filter out exempted findings, tracking applied and expired/stale exceptions.

        Returns:
            (unexempted_findings, applied_exception_ids, invalid_or_expired_exception_ids)
        """
        unexempted: list[HardenedFinding] = []
        applied_ids: set[str] = set()
        invalid_or_expired: set[str] = set()

        for finding in findings:
            exempted = False
            for exc in self._exceptions:
                if self.is_match(exc, finding):
                    if exc.is_expired(current_time_iso):
                        logger.warning(
                            "ChangeGuard exception '%s' for finding '%s' has expired on '%s'",
                            exc.exception_id,
                            finding.finding_id,
                            exc.expires_at,
                        )
                        invalid_or_expired.add(exc.exception_id)
                    else:
                        applied_ids.add(exc.exception_id)
                        exempted = True
                        break
            if not exempted:
                unexempted.append(finding)

        # Check for unreferenced / stale exceptions among active exceptions
        for exc in self._exceptions:
            if exc.exception_id not in applied_ids:
                if exc.is_expired(current_time_iso):
                    invalid_or_expired.add(exc.exception_id)
                else:
                    # Unmatched active exception (stale)
                    invalid_or_expired.add(f"{exc.exception_id}:stale")

        return tuple(unexempted), tuple(sorted(applied_ids)), tuple(sorted(invalid_or_expired))
