"""Configuration-related exceptions with user-friendly messages.

Provides structured exception classes for configuration errors,
with support for i18n messages and resolution guidance.

[INPUT]

[OUTPUT]
- ConfigIncompleteError: configuration incomplete error
- InvalidConfigError: configuration validation error
- ConfigValidationError: general configuration validation error

[POS]
Framework-level exception definitions. Business layer can inherit these
to create specific config error types (e.g., ProviderNotConfiguredError).
"""

from __future__ import annotations


class ConfigIncompleteError(Exception):
    """Configuration is incomplete or missing required items.

    This error should be raised when configuration checks fail at runtime.
    It carries user-friendly messages in multiple languages and resolution steps.

    Attributes:
        user_friendly_message: Dict of language code -> user message {en: "...", zh: "..."}
        technical_details: Technical error details for logging/debugging
        resolution_steps: List of actionable steps to fix the configuration
        error_code: Optional error code for frontend routing
    """

    def __init__(
        self,
        user_friendly_message: dict[str, str],
        technical_details: str,
        resolution_steps: list[str],
        error_code: str | None = None,
    ):
        self.user_friendly_message = user_friendly_message
        self.technical_details = technical_details
        self.resolution_steps = resolution_steps
        self.error_code = error_code or "config_incomplete"

        # Use English message as default exception message
        en_message = user_friendly_message.get("en", technical_details)
        super().__init__(en_message)

    def to_dict(self) -> dict[str, object]:
        """Export error as structured dictionary for API responses."""
        return {
            "error_type": self.error_code,
            "messages": self.user_friendly_message,
            "technical_details": self.technical_details,
            "resolution_steps": self.resolution_steps,
        }


class InvalidConfigError(Exception):
    """Configuration value is invalid or malformed.

    Raised when a configuration value fails validation (e.g., invalid model name,
    malformed URL, negative timeout value).
    """

    def __init__(self, field_name: str, reason: str):
        self.field_name = field_name
        self.reason = reason
        super().__init__(f"Invalid configuration field '{field_name}': {reason}")


class ConfigValidationError(Exception):
    """General configuration validation error.

    Raised when configuration fails validation checks (e.g., conflicting options,
    missing dependencies, dangerous combinations).
    """

    def __init__(self, message: str, issues: list[str] | None = None):
        self.issues = issues or []
        super().__init__(message)


__all__ = [
    "ConfigIncompleteError",
    "ConfigValidationError",
    "InvalidConfigError",
]
