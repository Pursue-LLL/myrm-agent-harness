"""Tests for configuration readiness checking system."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.config import ConfigIncompleteError, ConfigReadinessChecker, ConfigReadinessResult


class MockConfigChecker(ConfigReadinessChecker):
    """Mock implementation for testing."""

    def check(self, config: dict[str, object]) -> ConfigReadinessResult:
        """Check configuration."""
        enabled = config.get("enabled", False)
        if enabled:
            return ConfigReadinessResult(is_ready=True, missing_items=[], suggestions=[])
        return ConfigReadinessResult(
            is_ready=False, missing_items=["required_key"], suggestions=["Please configure required_key"]
        )


def test_readiness_result_ready() -> None:
    """Test ready configuration result."""
    result = ConfigReadinessResult(is_ready=True, missing_items=[], suggestions=[])
    assert result.is_ready is True
    assert len(result.missing_items) == 0
    assert len(result.suggestions) == 0


def test_readiness_result_not_ready() -> None:
    """Test not ready configuration result."""
    result = ConfigReadinessResult(
        is_ready=False, missing_items=["api_key", "endpoint"], suggestions=["Configure API key", "Configure endpoint"]
    )
    assert result.is_ready is False
    assert len(result.missing_items) == 2
    assert "api_key" in result.missing_items
    assert "endpoint" in result.missing_items
    assert len(result.suggestions) == 2


def test_checker_interface() -> None:
    """Test checker interface implementation."""
    checker = MockConfigChecker()

    # Test ready config
    ready_config = {"enabled": True}
    result = checker.check(ready_config)
    assert result.is_ready is True

    # Test not ready config
    not_ready_config = {"enabled": False}
    result = checker.check(not_ready_config)
    assert result.is_ready is False
    assert "required_key" in result.missing_items


def test_config_incomplete_error() -> None:
    """Test ConfigIncompleteError exception."""
    error = ConfigIncompleteError(
        user_friendly_message={"en": "Config incomplete", "zh": "配置不完整"},
        technical_details="Missing required keys",
        resolution_steps=["Step 1", "Step 2"],
        error_code="CONFIG_INCOMPLETE",
    )

    assert error.user_friendly_message["en"] == "Config incomplete"
    assert error.user_friendly_message["zh"] == "配置不完整"
    assert error.technical_details == "Missing required keys"
    assert len(error.resolution_steps) == 2
    assert error.error_code == "CONFIG_INCOMPLETE"


def test_config_incomplete_error_raise() -> None:
    """Test raising ConfigIncompleteError."""
    with pytest.raises(ConfigIncompleteError) as exc_info:
        raise ConfigIncompleteError(
            user_friendly_message={"en": "Test error"}, technical_details="Test details", resolution_steps=["Fix it"]
        )

    error = exc_info.value
    assert error.user_friendly_message["en"] == "Test error"
    assert error.technical_details == "Test details"
    assert error.resolution_steps[0] == "Fix it"


def test_config_incomplete_error_default_code() -> None:
    """Test ConfigIncompleteError with default error code."""
    error = ConfigIncompleteError(
        user_friendly_message={"en": "Error"}, technical_details="Details", resolution_steps=[]
    )

    assert error.error_code == "config_incomplete"
