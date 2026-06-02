"""Message filtering framework for AI safety and compliance.

This module provides a flexible, composable framework for filtering messages
in AI conversations. It's designed to support various filtering needs:

- System prompt hiding (security)
- PII redaction (privacy)
- Custom content filtering (compliance)

Architecture:
- FilterConfig: Configuration for filters
- FilterContext: Runtime context (user_id, api_key, etc.)
- MessageFilter: Abstract base class for filters
- SystemRoleFilter: Filter system role messages
- MessageFilterPipeline: Compose multiple filters

Example:
    >>> from myrm_agent_harness.agent.security.message_filtering import (
    ...     SystemRoleFilter,
    ...     MessageFilterPipeline,
    ...     FilterConfig,
    ...     FilterContext,
    ... )
    >>>
    >>> config = FilterConfig(enabled=True, whitelist_api_keys={'admin-key'})
    >>> pipeline = MessageFilterPipeline([
    ...     SystemRoleFilter(config),
    ... ])
    >>>
    >>> messages = [
    ...     {'role': 'system', 'content': 'You are...'},
    ...     {'role': 'user', 'content': 'Hello'},
    ... ]
    >>> context = FilterContext(user_id='user-123', api_key='user-key')
    >>> filtered = pipeline.filter_messages(messages, context)
    >>> # Result: only user message
"""

from .base import FilterConfig, FilterContext, MessageFilter
from .config_manager import ConfigManager, MemoryConfigManager
from .credential_leak_filter import CredentialLeakFilter
from .filter_stats import FilterStats
from .pii_redaction_filter import PIIRedactionFilter
from .pipeline import MessageFilterPipeline
from .system_role_filter import SystemRoleFilter

__all__ = [
    "ConfigManager",
    "CredentialLeakFilter",
    "FilterConfig",
    "FilterContext",
    "FilterStats",
    "MemoryConfigManager",
    "MessageFilter",
    "MessageFilterPipeline",
    "PIIRedactionFilter",
    "SystemRoleFilter",
]
