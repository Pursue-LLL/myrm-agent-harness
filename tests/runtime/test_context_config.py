"""Tests for context configuration validation."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.config import (
    ContextCleanupConfig,
    StorageQuotaConfig,
)


def test_cleanup_config_valid() -> None:
    """Test valid cleanup configuration."""
    config = ContextCleanupConfig(
        max_age_days=7,
        session_active_days=30,
        file_access_days=14,
        batch_size=100,
        timeout_seconds=1800.0,
    )

    assert config.max_age_days == 7
    assert config.session_active_days == 30
    assert config.file_access_days == 14


def test_cleanup_config_invalid_max_age() -> None:
    """Test invalid max_age_days raises ValueError."""
    with pytest.raises(ValueError, match="max_age_days must be positive"):
        ContextCleanupConfig(max_age_days=0)


def test_cleanup_config_invalid_session_active() -> None:
    """Test invalid session_active_days raises ValueError."""
    with pytest.raises(ValueError, match="session_active_days must be positive"):
        ContextCleanupConfig(session_active_days=-1)


def test_cleanup_config_invalid_file_access() -> None:
    """Test invalid file_access_days raises ValueError."""
    with pytest.raises(ValueError, match="file_access_days must be positive"):
        ContextCleanupConfig(file_access_days=0)


def test_cleanup_config_inconsistent_thresholds() -> None:
    """Test inconsistent threshold values raise ValueError."""
    with pytest.raises(ValueError, match="session_active_days.*should be >=.*file_access_days"):
        ContextCleanupConfig(
            session_active_days=10,
            file_access_days=20,
        )


def test_cleanup_config_inconsistent_fallback() -> None:
    """Test inconsistent fallback threshold raises ValueError."""
    with pytest.raises(ValueError, match="file_access_days.*should be >=.*max_age_days"):
        ContextCleanupConfig(
            max_age_days=20,
            file_access_days=10,
        )


def test_cleanup_config_invalid_batch_size() -> None:
    """Test invalid batch_size raises ValueError."""
    with pytest.raises(ValueError, match="batch_size must be positive"):
        ContextCleanupConfig(batch_size=0)


def test_cleanup_config_invalid_timeout() -> None:
    """Test invalid timeout_seconds raises ValueError."""
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        ContextCleanupConfig(timeout_seconds=-1.0)


def test_quota_config_valid() -> None:
    """Test valid quota configuration."""
    config = StorageQuotaConfig(
        per_session_limit_mb=500,
        auto_cleanup_threshold=0.8,
    )

    assert config.per_session_limit_mb == 500
    assert config.auto_cleanup_threshold == 0.8


def test_quota_config_invalid_limit() -> None:
    """Test invalid per_session_limit_mb raises ValueError."""
    with pytest.raises(ValueError, match="per_session_limit_mb must be positive"):
        StorageQuotaConfig(per_session_limit_mb=0)


def test_quota_config_invalid_threshold_too_low() -> None:
    """Test invalid auto_cleanup_threshold (too low) raises ValueError."""
    with pytest.raises(ValueError, match="auto_cleanup_threshold must be in"):
        StorageQuotaConfig(auto_cleanup_threshold=0.0)


def test_quota_config_invalid_threshold_too_high() -> None:
    """Test invalid auto_cleanup_threshold (too high) raises ValueError."""
    with pytest.raises(ValueError, match="auto_cleanup_threshold must be in"):
        StorageQuotaConfig(auto_cleanup_threshold=1.0)


def test_quota_config_invalid_threshold_negative() -> None:
    """Test invalid auto_cleanup_threshold (negative) raises ValueError."""
    with pytest.raises(ValueError, match="auto_cleanup_threshold must be in"):
        StorageQuotaConfig(auto_cleanup_threshold=-0.1)


def test_cleanup_config_defaults() -> None:
    """Test cleanup config with default values."""
    config = ContextCleanupConfig()

    assert config.max_age_days == 7
    assert config.session_active_days == 30
    assert config.file_access_days == 14


def test_cleanup_config_custom() -> None:
    """Test cleanup config with custom values."""
    config = ContextCleanupConfig(
        max_age_days=14,
        session_active_days=60,
        file_access_days=28,
    )

    assert config.max_age_days == 14
    assert config.session_active_days == 60
    assert config.file_access_days == 28
