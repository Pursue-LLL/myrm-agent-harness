"""Credential leak filter for message security.

Detects and blocks messages containing credentials (API keys, tokens, passwords)
using the agent security framework's leak detector.

[INPUT]
- (none)

[OUTPUT]
- CredentialLeakFilter: Filter that detects and blocks credential leaks in messages.

[POS]
Credential leak filter for message security.
"""

from typing import Any

from ..audit import record_decision
from ..detection.leak_detector import scan_for_leaks
from .base import FilterConfig, FilterContext, MessageFilter


class CredentialLeakFilter(MessageFilter):
    """Filter that detects and blocks credential leaks in messages.

    Credentials include:
    - API keys (AWS, OpenAI, Anthropic, etc.)
    - Tokens (GitHub, Slack, JWT)
    - Passwords and secrets
    - Private keys and certificates

    This filter always blocks messages containing credentials (no redaction mode)
    because credential leaks represent a critical security risk (S3 level).

    Uses the security framework's leak_detector for pattern matching against
    25+ credential types.

    Example:
        >>> config = FilterConfig(enabled=True, audit_enabled=True)
        >>> filter = CredentialLeakFilter(config)
        >>>
        >>> message = {'role': 'user', 'content': 'My key is sk-abcd1234...'}
        >>> context = FilterContext(user_id='user-123')
        >>>
        >>> filtered = filter.filter(message, context)
        >>> # filtered == None (message blocked)
    """

    def __init__(self, config: FilterConfig):
        """Initialize CredentialLeakFilter.

        Args:
            config: Filter configuration
        """
        self.config = config

    def should_filter(self, message: dict[str, Any], context: FilterContext) -> bool:
        """Determine if message contains credential leaks.

        Args:
            message: Message to evaluate
            context: Runtime context

        Returns:
            True if credentials detected (message should be blocked), False otherwise
        """
        if not self.config.enabled:
            return False

        content = message.get("content", "")
        if not isinstance(content, str) or len(content) < 16:
            return False

        leak_patterns = scan_for_leaks(content)

        if leak_patterns:
            # Credential leak detected - record audit event
            if self.config.audit_enabled:
                record_decision(
                    tool_name="CredentialLeakFilter",
                    decision="CREDENTIAL_LEAK_DETECTED",
                    reason=f"Detected credential leak: {', '.join(leak_patterns[:3])}",
                )
                record_decision(
                    tool_name="CredentialLeakFilter",
                    decision="CREDENTIAL_LEAK_BLOCKED",
                    reason="Message blocked due to credential leak (S3 level)",
                )
            return True

        return False

    def filter(self, message: dict[str, Any], context: FilterContext) -> dict[str, Any] | None:
        """Apply credential leak filtering to a message.

        Args:
            message: Message to filter
            context: Runtime context

        Returns:
            None if credentials detected (message blocked), otherwise original message
        """
        if not self.config.enabled:
            return message

        content = message.get("content", "")
        if not isinstance(content, str) or len(content) < 16:
            return message

        leak_patterns = scan_for_leaks(content)

        if leak_patterns:
            # Block message completely
            if self.config.audit_enabled:
                record_decision(
                    tool_name="CredentialLeakFilter",
                    decision="CREDENTIAL_LEAK_DETECTED",
                    reason=f"Detected credential leak: {', '.join(leak_patterns[:3])}",
                )
                record_decision(
                    tool_name="CredentialLeakFilter",
                    decision="CREDENTIAL_LEAK_BLOCKED",
                    reason="Message blocked due to credential leak (S3 level)",
                )
            return None

        return message
