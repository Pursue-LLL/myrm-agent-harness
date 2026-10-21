"""Unit tests for MessageFilterPipeline."""

import pytest

from myrm_agent_harness.agent.security.message_filtering import (
    FilterConfig,
    FilterContext,
    MessageFilter,
    MessageFilterPipeline,
    SystemRoleFilter,
)


class CustomTestFilter(MessageFilter):
    """Custom filter for testing pipeline composition."""

    def __init__(self, filter_pattern: str):
        self.filter_pattern = filter_pattern

    def should_filter(self, message, context):
        return self.filter_pattern in message.get("content", "")


@pytest.fixture
def default_config():
    """Default filter configuration."""
    return FilterConfig(enabled=True, audit_enabled=False)


@pytest.fixture
def default_context():
    """Default filter context."""
    return FilterContext(user_id="user-123")


def test_pipeline_with_single_filter(default_config, default_context):
    """Pipeline with single filter should work."""
    pipeline = MessageFilterPipeline(
        [
            SystemRoleFilter(default_config),
        ]
    )

    messages = [
        {"role": "system", "content": "You are..."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
    ]

    filtered = pipeline.filter_messages(messages, default_context)

    assert len(filtered) == 2
    assert filtered[0]["role"] == "user"
    assert filtered[1]["role"] == "assistant"


def test_pipeline_with_multiple_filters(default_config, default_context):
    """Pipeline with multiple filters should apply all."""
    pipeline = MessageFilterPipeline(
        [
            SystemRoleFilter(default_config),
            CustomTestFilter("[SENSITIVE]"),
        ]
    )

    messages = [
        {"role": "system", "content": "You are..."},
        {"role": "user", "content": "Hello"},
        {"role": "user", "content": "[SENSITIVE] data"},
        {"role": "assistant", "content": "Hi!"},
    ]

    filtered = pipeline.filter_messages(messages, default_context)

    # Should filter: system message + sensitive message
    assert len(filtered) == 2
    assert filtered[0]["content"] == "Hello"
    assert filtered[1]["content"] == "Hi!"


def test_pipeline_short_circuit(default_config, default_context):
    """Pipeline should short-circuit on first match."""
    call_counts = []

    class CountingFilter(MessageFilter):
        def __init__(self, name):
            self.name = name

        def should_filter(self, message, context):
            call_counts.append(self.name)
            return self.name == "filter1" and message["role"] == "system"

    pipeline = MessageFilterPipeline(
        [
            CountingFilter("filter1"),
            CountingFilter("filter2"),
        ]
    )

    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "User"},
    ]

    filtered = pipeline.filter_messages(messages, default_context)

    # System message: filter1 matches, filter2 not called (short-circuit)
    # User message: both filters called
    assert len(filtered) == 1
    assert "filter1" in call_counts
    assert "filter2" in call_counts


def test_pipeline_add_filter(default_config, default_context):
    """Should be able to add filter dynamically."""
    pipeline = MessageFilterPipeline(
        [
            SystemRoleFilter(default_config),
        ]
    )

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "user", "content": "[SENSITIVE]"},
    ]

    # Before adding custom filter
    filtered = pipeline.filter_messages(messages, default_context)
    assert len(filtered) == 2

    # Add custom filter
    pipeline.add_filter(CustomTestFilter("[SENSITIVE]"))

    # After adding
    filtered = pipeline.filter_messages(messages, default_context)
    assert len(filtered) == 1


def test_pipeline_remove_filter(default_config, default_context):
    """Should be able to remove filter by name."""
    pipeline = MessageFilterPipeline(
        [
            SystemRoleFilter(default_config),
            CustomTestFilter("[SENSITIVE]"),
        ]
    )

    messages = [
        {"role": "user", "content": "[SENSITIVE]"},
    ]

    # Before removing
    filtered = pipeline.filter_messages(messages, default_context)
    assert len(filtered) == 0  # Filtered by CustomTestFilter

    # Remove custom filter
    removed = pipeline.remove_filter("CustomTestFilter")
    assert removed is True

    # After removing
    filtered = pipeline.filter_messages(messages, default_context)
    assert len(filtered) == 1


def test_pipeline_get_filter_names(default_config):
    """Should return list of filter names."""
    pipeline = MessageFilterPipeline(
        [
            SystemRoleFilter(default_config),
            CustomTestFilter("[TEST]"),
        ]
    )

    names = pipeline.get_filter_names()

    assert "SystemRoleFilter" in names
    assert "CustomTestFilter" in names
    assert len(names) == 2


def test_empty_pipeline(default_context):
    """Empty pipeline should not filter anything."""
    pipeline = MessageFilterPipeline([])

    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "User"},
    ]

    filtered = pipeline.filter_messages(messages, default_context)

    assert len(filtered) == 2


def test_pipeline_preserves_order(default_config, default_context):
    """Pipeline should preserve message order."""
    pipeline = MessageFilterPipeline(
        [
            SystemRoleFilter(default_config),
        ]
    )

    messages = [
        {"role": "user", "content": "First", "id": 1},
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Second", "id": 2},
        {"role": "assistant", "content": "Response", "id": 3},
    ]

    filtered = pipeline.filter_messages(messages, default_context)

    assert len(filtered) == 3
    assert filtered[0]["id"] == 1
    assert filtered[1]["id"] == 2
    assert filtered[2]["id"] == 3
