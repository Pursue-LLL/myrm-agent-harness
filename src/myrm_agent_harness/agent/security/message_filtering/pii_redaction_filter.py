"""PII redaction filter for message sanitization.

Detects and redacts/blocks personally identifiable information in messages
using the agent security framework's PII classifier and redactor.

[INPUT]
- (none)

[OUTPUT]
- PIIRedactionFilter: Filter that detects and redacts/blocks PII in messages.

[POS]
PII redaction filter for message sanitization.
"""

from typing import Any

from ..audit import record_decision
from ..detection.pii_classifier import classify_content
from ..detection.pii_redactor import redact_pii
from ..types import PrivacyPolicy, SensitivityLevel
from .base import FilterConfig, FilterContext, MessageFilter


class PIIRedactionFilter(MessageFilter):
    """Filter that detects and redacts/blocks PII in messages.

    Supports two modes:
    - "redact": Replace PII with masked placeholders (e.g., 138****5678)
    - "block": Completely hide messages containing PII

    Uses the security framework's PIIClassifier for detection and PIIRedactor
    for type-aware redaction.

    Example:
        >>> config = FilterConfig(enabled=True, audit_enabled=True)
        >>> policy = PrivacyPolicy(enabled=True)
        >>> filter = PIIRedactionFilter(config, policy, mode="redact")
        >>>
        >>> message = {'role': 'user', 'content': '我的手机是13812345678'}
        >>> context = FilterContext(user_id='user-123')
        >>>
        >>> filtered = filter.filter(message, context)
        >>> # filtered['content'] == '我的手机是138****5678 [PII:phone]'
    """

    def __init__(self, config: FilterConfig, policy: PrivacyPolicy, mode: str = "redact"):
        """Initialize PIIRedactionFilter.

        Args:
            config: Filter configuration
            policy: Privacy policy for PII detection
            mode: "redact" (mask PII) or "block" (hide message)
        """
        if mode not in ("redact", "block"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'redact' or 'block'")

        self.config = config
        self.policy = policy
        self.mode = mode

    def should_filter(self, message: dict[str, Any], context: FilterContext) -> bool:
        """Determine if message contains PII that should be filtered.

        Args:
            message: Message to evaluate
            context: Runtime context

        Returns:
            True if message should be hidden (block mode only), False otherwise
        """
        if not self.config.enabled or not self.policy.enabled:
            return False

        content = message.get("content", "")
        if not isinstance(content, str) or len(content) < 6:
            return False

        classification = classify_content(content, self.policy)

        # No PII detected
        if classification.level == SensitivityLevel.S1:
            return False

        # PII detected - record audit event
        if self.config.audit_enabled:
            record_decision(
                tool_name="PIIRedactionFilter",
                decision="PII_DETECTED",
                reason=f"Detected {classification.level.name} PII: {', '.join(classification.patterns[:3])}",
            )

        # Block mode: completely hide message
        if self.mode == "block":
            if self.config.audit_enabled:
                record_decision(
                    tool_name="PIIRedactionFilter",
                    decision="PII_BLOCKED",
                    reason=f"Message blocked due to {classification.level.name} PII",
                )
            return True

        # Redact mode: handled in filter() method
        return False

    def filter(self, message: dict[str, Any], context: FilterContext) -> dict[str, Any] | None:
        """Apply PII filtering to a message.

        Args:
            message: Message to filter
            context: Runtime context

        Returns:
            Filtered message (with redacted PII) or None (if blocked)
        """
        if not self.config.enabled or not self.policy.enabled:
            return message

        content = message.get("content", "")
        if not isinstance(content, str) or len(content) < 6:
            return message

        classification = classify_content(content, self.policy)

        # No PII detected
        if classification.level == SensitivityLevel.S1:
            return message

        # Block mode: return None to hide message
        if self.mode == "block":
            if self.config.audit_enabled:
                record_decision(
                    tool_name="PIIRedactionFilter",
                    decision="PII_BLOCKED",
                    reason=f"Message blocked due to {classification.level.name} PII",
                )
            return None

        # Redact mode: mask PII
        redacted_content, redact_count = redact_pii(content)

        if redact_count > 0:
            if self.config.audit_enabled:
                record_decision(
                    tool_name="PIIRedactionFilter",
                    decision="PII_REDACTED",
                    reason=f"Redacted {redact_count} PII instances: {', '.join(classification.patterns[:3])}",
                )

            # Return message with redacted content
            filtered_message = message.copy()
            filtered_message["content"] = redacted_content
            return filtered_message

        return message
