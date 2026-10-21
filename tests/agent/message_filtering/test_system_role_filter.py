"""Unit tests for SystemRoleFilter."""

from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.security.message_filtering import FilterConfig, FilterContext, SystemRoleFilter


@pytest.fixture
def default_config():
    """Default filter configuration."""
    return FilterConfig(enabled=True, whitelist_api_keys={"admin-key", "debug-key"}, audit_enabled=True)


@pytest.fixture
def default_context():
    """Default filter context."""
    return FilterContext(user_id="user-123", api_key="user-key")


@patch("myrm_agent_harness.agent.security.message_filtering.system_role_filter.record_decision")
def test_filter_system_message(mock_record, default_config, default_context):
    """System role messages should be filtered by default."""
    filter = SystemRoleFilter(default_config)

    message = {"role": "system", "content": "You are an AI assistant..."}

    assert filter.should_filter(message, default_context) is True
    # Verify audit log
    assert mock_record.called


@patch("myrm_agent_harness.agent.security.message_filtering.system_role_filter.record_decision")
def test_allow_user_message(mock_record, default_config, default_context):
    """User messages should not be filtered."""
    filter = SystemRoleFilter(default_config)

    message = {"role": "user", "content": "Hello"}

    assert filter.should_filter(message, default_context) is False
    # No audit log for non-system messages
    assert not mock_record.called


@patch("myrm_agent_harness.agent.security.message_filtering.system_role_filter.record_decision")
def test_allow_assistant_message(mock_record, default_config, default_context):
    """Assistant messages should not be filtered."""
    filter = SystemRoleFilter(default_config)

    message = {"role": "assistant", "content": "Hi! How can I help?"}

    assert filter.should_filter(message, default_context) is False


@patch("myrm_agent_harness.agent.security.message_filtering.system_role_filter.record_decision")
def test_whitelist_allows_system_message(mock_record, default_config):
    """Whitelisted API keys should bypass filtering."""
    filter = SystemRoleFilter(default_config)

    admin_context = FilterContext(user_id="admin", api_key="admin-key")
    message = {"role": "system", "content": "You are..."}

    assert filter.should_filter(message, admin_context) is False
    # Verify audit log for allowed access
    assert mock_record.called


@patch("myrm_agent_harness.agent.security.message_filtering.system_role_filter.record_decision")
def test_disabled_filter_allows_all(mock_record, default_context):
    """Disabled filter should allow all messages."""
    config = FilterConfig(enabled=False)
    filter = SystemRoleFilter(config)

    message = {"role": "system", "content": "You are..."}

    assert filter.should_filter(message, default_context) is False


@patch("myrm_agent_harness.agent.security.message_filtering.system_role_filter.record_decision")
def test_no_audit_logger(mock_record, default_config, default_context):
    """Filter should work without audit logger."""
    filter = SystemRoleFilter(default_config)

    message = {"role": "system", "content": "You are..."}

    # Should still filter, just without logging
    assert filter.should_filter(message, default_context) is True


@patch("myrm_agent_harness.agent.security.message_filtering.system_role_filter.record_decision")
def test_audit_disabled(mock_record, default_context):
    """Audit disabled should not log events."""
    config = FilterConfig(enabled=True, audit_enabled=False)
    filter = SystemRoleFilter(config)

    message = {"role": "system", "content": "You are..."}

    assert filter.should_filter(message, default_context) is True
    # No audit log when disabled
    assert not mock_record.called


@patch("myrm_agent_harness.agent.security.message_filtering.system_role_filter.record_decision")
def test_whitelist_with_debug_key(mock_record, default_config):
    """Debug key should also bypass filtering."""
    filter = SystemRoleFilter(default_config)

    debug_context = FilterContext(user_id="developer", api_key="debug-key")
    message = {"role": "system", "content": "You are..."}

    assert filter.should_filter(message, debug_context) is False
    assert mock_record.called


def test_context_metadata(default_config):
    """Context metadata should be available for custom logic."""
    filter = SystemRoleFilter(default_config)

    context = FilterContext(
        user_id="user-123", api_key="user-key", request_id="req-456", metadata={"tenant_id": "org-789"}
    )
    message = {"role": "system", "content": "You are..."}

    assert filter.should_filter(message, context) is True
    # Metadata is available in context
    assert context.metadata["tenant_id"] == "org-789"
