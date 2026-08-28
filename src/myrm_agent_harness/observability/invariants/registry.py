"""Runtime Invariant Registry Service.

[INPUT]
- myrm_agent_harness.observability.invariants.types::(InvariantViolation, InvariantSeverity, InvariantCheckerProtocol) (POS: 不变式基础类型契约)

[OUTPUT]
- InvariantError: Specific exception raised on fatal invariant breach in strict mode
- InvariantMode: Mode enum (STRICT, WARN, DISABLED)
- RuntimeInvariantRegistry: Central manager for registering and executing runtime invariant checks

[POS]
Central registry service that stores and coordinates package-owned runtime invariant assertions.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Callable, Sequence

from myrm_agent_harness.observability.invariants.types import (
    InvariantCheckerProtocol,
    InvariantSeverity,
    InvariantViolation,
)

logger = logging.getLogger(__name__)


class InvariantError(RuntimeError):
    """Exception raised when an invariant check fails in STRICT mode."""

    def __init__(self, violation: InvariantViolation) -> None:
        self.violation = violation
        self.code = violation.code
        super().__init__(
            f"[{violation.code}:{violation.package_name}:{violation.invariant_name}] "
            f"{violation.message}"
        )


class InvariantMode(str, Enum):
    """Execution mode for runtime invariants."""

    STRICT = "STRICT"  # Raises InvariantError immediately on first ERROR violation
    WARN = "WARN"      # Logs violations and returns list without interrupting flow
    DISABLED = "DISABLED"  # Completely bypasses execution for 0-overhead production


class RuntimeInvariantRegistry:
    """Configurable registry service for package-owned runtime invariant checks."""

    def __init__(
        self,
        *,
        mode: InvariantMode = InvariantMode.WARN,
        allowlist_pattern: str | None = None,
        blocklist_pattern: str | None = None,
    ) -> None:
        self._mode = mode
        self._allowlist_re = re.compile(allowlist_pattern) if allowlist_pattern else None
        self._blocklist_re = re.compile(blocklist_pattern) if blocklist_pattern else None
        # Map: package_name -> list of (invariant_name, checker_callable)
        self._checkers: dict[str, list[tuple[str, InvariantCheckerProtocol]]] = {}
        self._recorded_violations: list[InvariantViolation] = []

    @property
    def mode(self) -> InvariantMode:
        """Current operational mode."""
        return self._mode

    def set_mode(self, mode: InvariantMode) -> None:
        """Update invariant checking mode."""
        self._mode = mode

    def register(
        self,
        package_name: str,
        invariant_name: str,
        checker: InvariantCheckerProtocol,
    ) -> None:
        """Register a runtime invariant checker for a given package."""
        if package_name not in self._checkers:
            self._checkers[package_name] = []
        self._checkers[package_name].append((invariant_name, checker))

    def unregister_package(self, package_name: str) -> bool:
        """Remove all registered checkers for a package."""
        return self._checkers.pop(package_name, None) is not None

    def clear(self) -> None:
        """Clear all registered checkers and recorded violations."""
        self._checkers.clear()
        self._recorded_violations.clear()

    @property
    def registered_packages(self) -> list[str]:
        """List of all packages with active invariant checkers."""
        return list(self._checkers.keys())

    @property
    def total_checkers_count(self) -> int:
        """Total number of individual invariant checkers registered."""
        return sum(len(checkers) for checkers in self._checkers.values())

    def get_recorded_violations(self) -> list[InvariantViolation]:
        """Return a copy of all accumulated violations across runs."""
        return list(self._recorded_violations)

    def _should_run_package(self, package_name: str) -> bool:
        """Evaluate allowlist / blocklist regex filters."""
        if self._mode == InvariantMode.DISABLED:
            return False
        if self._blocklist_re and self._blocklist_re.search(package_name):
            return False
        if self._allowlist_re and not self._allowlist_re.search(package_name):
            return False
        return True

    def check_package(
        self,
        package_name: str,
        context: object,
        *,
        override_mode: InvariantMode | None = None,
    ) -> list[InvariantViolation]:
        """Run all invariant checkers registered for a specific package against context."""
        effective_mode = override_mode or self._mode
        if effective_mode == InvariantMode.DISABLED:
            return []

        if not self._should_run_package(package_name):
            return []

        checkers = self._checkers.get(package_name, [])
        violations: list[InvariantViolation] = []

        for invariant_name, checker in checkers:
            try:
                results = checker(context)
                if results:
                    for v in results:
                        violations.append(v)
                        self._recorded_violations.append(v)
                        if v.severity == InvariantSeverity.ERROR:
                            logger.error(
                                "Runtime Invariant Violation [%s:%s]: %s",
                                v.package_name,
                                v.invariant_name,
                                v.message,
                            )
                            if effective_mode == InvariantMode.STRICT:
                                raise InvariantError(v)
                        else:
                            logger.warning(
                                "Runtime Invariant Warning [%s:%s]: %s",
                                v.package_name,
                                v.invariant_name,
                                v.message,
                            )
            except InvariantError:
                raise
            except Exception as exc:
                logger.exception(
                    "Error executing invariant checker [%s:%s]: %s",
                    package_name,
                    invariant_name,
                    exc,
                )

        return violations

    def check_all(
        self,
        context: object,
        *,
        override_mode: InvariantMode | None = None,
    ) -> list[InvariantViolation]:
        """Run all registered invariant checkers across all active packages."""
        effective_mode = override_mode or self._mode
        if effective_mode == InvariantMode.DISABLED:
            return []

        all_violations: list[InvariantViolation] = []
        for pkg in list(self._checkers.keys()):
            violations = self.check_package(pkg, context, override_mode=effective_mode)
            all_violations.extend(violations)
        return all_violations


# Global default registry singleton
default_invariant_registry = RuntimeInvariantRegistry(mode=InvariantMode.WARN)
