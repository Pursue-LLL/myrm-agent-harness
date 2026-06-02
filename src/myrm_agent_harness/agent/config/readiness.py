"""Configuration readiness checking system.

Provides abstract base classes and interfaces for checking configuration completeness.
Business layer can inherit these interfaces to implement specific readiness checks.

[INPUT]

[OUTPUT]
- ConfigReadinessResult: structured readiness check result
- ConfigReadinessChecker: abstract interface for readiness checks

[POS]
Framework-level readiness check infrastructure. Business layer inherits to implement
specific checks (e.g., provider availability, API key validation).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class ConfigReadinessResult:
    """Result of a configuration readiness check.

    Attributes:
        is_ready: True if configuration is complete and ready
        missing_items: List of missing or invalid configuration items
        suggestions: List of suggestions to fix configuration issues
        extra_info: Optional additional information (error details, etc.)
    """

    is_ready: bool
    missing_items: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    extra_info: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        """Export readiness result as dictionary."""
        return {
            "is_ready": self.is_ready,
            "missing_items": list(self.missing_items),
            "suggestions": list(self.suggestions),
            "extra_info": self.extra_info or {},
        }


class ConfigReadinessChecker(ABC):
    """Abstract base class for configuration readiness checks.

    Business layer should inherit this class and implement the check() method
    to provide specific readiness validation logic.

    Example:
        class ProviderConfigChecker(ConfigReadinessChecker):
            def check(self, config: dict) -> ConfigReadinessResult:
                # Check if provider is configured
                if not config.get("providers"):
                    return ConfigReadinessResult(
                        is_ready=False,
                        missing_items=["providers"],
                        suggestions=["Configure at least one LLM provider"]
                    )
                return ConfigReadinessResult(is_ready=True)
    """

    @abstractmethod
    def check(self, config: dict[str, object] | None = None) -> ConfigReadinessResult:
        """Check configuration readiness.

        Args:
            config: Optional configuration dictionary to check

        Returns:
            ConfigReadinessResult with readiness status, missing items, and suggestions
        """
        pass


__all__ = [
    "ConfigReadinessChecker",
    "ConfigReadinessResult",
]
