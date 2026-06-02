"""Base classes for message filtering framework.

[INPUT]
- (none)

[OUTPUT]
- FilterConfig: Configuration for message filters.
- FilterContext: Runtime context for filtering decisions.
- MessageFilter: Abstract base class for message filters.

[POS]
Base classes for message filtering framework.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FilterConfig:
    """Configuration for message filters.

    Attributes:
        enabled: Whether filtering is enabled. Defaults to True.
        whitelist_api_keys: Set of API keys that bypass filtering (e.g., admin keys).
        audit_enabled: Whether to log filtering events for security audit.
    """

    enabled: bool = True
    whitelist_api_keys: set[str] = field(default_factory=set)
    audit_enabled: bool = True


@dataclass
class FilterContext:
    """Runtime context for filtering decisions.

    This context is passed to each filter to enable context-aware filtering,
    such as whitelisting certain users or logging security events.

    Attributes:
        user_id: Unique identifier of the user making the request.
        api_key: Optional API key for authentication (used for whitelist checks).
        request_id: Optional request ID for audit logging correlation.
        metadata: Optional metadata for custom filtering logic.
    """

    user_id: str
    api_key: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MessageFilter(ABC):
    """Abstract base class for message filters.

    A filter decides whether a message should be filtered out (hidden) based on
    its content and context. Filters can be composed into a pipeline.

    Subclasses must implement:
        - should_filter(): Return True if the message should be filtered out.

    Example:
        >>> class CustomFilter(MessageFilter):
        ...     def should_filter(self, message, context):
        ...         return message.get('sensitive') is True
    """

    @abstractmethod
    def should_filter(self, message: dict[str, Any], context: FilterContext) -> bool:
        """Determine if a message should be filtered out.

        Args:
            message: Message to evaluate (dict with 'role', 'content', etc.)
            context: Runtime context for filtering decision

        Returns:
            True if the message should be hidden, False to keep it
        """
        pass

    def get_name(self) -> str:
        """Get the filter name for logging/debugging.

        Returns:
            Human-readable filter name (defaults to class name)
        """
        return self.__class__.__name__
