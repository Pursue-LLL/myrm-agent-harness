"""System role message filter for AI safety.

[INPUT]
- (none)

[OUTPUT]
- SystemRoleFilter: Filter that hides system role messages.

[POS]
System role message filter for AI safety.
"""

from typing import Any

from ..audit import record_decision
from .base import FilterConfig, FilterContext, MessageFilter


class SystemRoleFilter(MessageFilter):
    """Filter that hides system role messages.

    System prompts contain sensitive AI behavior instructions and should not
    be exposed to end users. This filter implements a multi-layer defense:

    1. Configuration: Can be disabled via FilterConfig
    2. Whitelist: Certain API keys (admin, debug tools) can bypass filtering
    3. Audit: All filtering events are logged for security monitoring

    Security rationale:
    - Prevent information leakage of AI instructions
    - Support legitimate access (admin, debugging)
    - Enable security observability via audit logs

    Example:
        >>> config = FilterConfig(
        ...     enabled=True,
        ...     whitelist_api_keys={'admin-key'},
        ...     audit_enabled=True,
        ... )
        >>> filter = SystemRoleFilter(config, audit_logger=logger)
        >>>
        >>> message = {'role': 'system', 'content': 'You are an AI...'}
        >>> context = FilterContext(user_id='user-123', api_key='user-key')
        >>>
        >>> filter.should_filter(message, context)  # True (filtered)
        >>>
        >>> admin_context = FilterContext(user_id='admin', api_key='admin-key')
        >>> filter.should_filter(message, admin_context)  # False (whitelisted)
    """

    def __init__(self, config: FilterConfig):
        """Initialize SystemRoleFilter.

        Args:
            config: Filter configuration
        """
        self.config = config

    def should_filter(self, message: dict[str, Any], context: FilterContext) -> bool:
        """Determine if a system role message should be filtered.

        Args:
            message: Message to evaluate
            context: Runtime context

        Returns:
            True if message should be hidden, False otherwise
        """
        # Only filter system role messages
        if message.get("role") != "system":
            return False

        # Check if filtering is disabled globally
        if not self.config.enabled:
            return False

        # Whitelist check: certain API keys can see system messages
        if context.api_key in self.config.whitelist_api_keys:
            if self.config.audit_enabled:
                record_decision(
                    tool_name="SystemRoleFilter",
                    decision="MESSAGE_ALLOWED",
                    reason=f"Whitelisted API key: user_id={context.user_id}, api_key={context.api_key[:8]}***",
                )
            return False

        # Filter the system message and record audit event
        if self.config.audit_enabled:
            record_decision(
                tool_name="SystemRoleFilter",
                decision="MESSAGE_FILTERED",
                reason=f"System role message filtered: user_id={context.user_id}",
            )

        return True
