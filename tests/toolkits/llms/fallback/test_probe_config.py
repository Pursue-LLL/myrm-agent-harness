"""Tests for ProbeConfig and configurable probe behavior."""

import pytest

from myrm_agent_harness.toolkits.llms.fallback import (
    PRESET_CONFIGS,
    ProbeConfig,
    get_preset_config,
)


def test_probe_config_defaults():
    """Test ProbeConfig default values."""
    config = ProbeConfig()

    assert config.cooldown_ms == 30_000
    assert config.probe_interval_ms == 30_000
    assert config.max_probe_attempts == 3
    assert config.global_throttle_ms == 30_000


def test_probe_config_custom_values():
    """Test ProbeConfig with custom values."""
    config = ProbeConfig(
        cooldown_ms=60_000,
        probe_interval_ms=45_000,
        max_probe_attempts=5,
        global_throttle_ms=50_000,
    )

    assert config.cooldown_ms == 60_000
    assert config.probe_interval_ms == 45_000
    assert config.max_probe_attempts == 5
    assert config.global_throttle_ms == 50_000


def test_probe_config_validation_negative_cooldown():
    """Test that negative cooldown raises error."""
    with pytest.raises(ValueError, match="cooldown_ms must be non-negative"):
        ProbeConfig(cooldown_ms=-1000)


def test_probe_config_validation_negative_interval():
    """Test that negative probe interval raises error."""
    with pytest.raises(ValueError, match="probe_interval_ms must be non-negative"):
        ProbeConfig(probe_interval_ms=-5000)


def test_probe_config_validation_zero_attempts():
    """Test that zero max attempts raises error."""
    with pytest.raises(ValueError, match="max_probe_attempts must be at least 1"):
        ProbeConfig(max_probe_attempts=0)


def test_probe_config_validation_negative_throttle():
    """Test that negative global throttle raises error."""
    with pytest.raises(ValueError, match="global_throttle_ms must be non-negative"):
        ProbeConfig(global_throttle_ms=-1000)


def test_get_preset_config_default():
    """Test getting default preset config."""
    config = get_preset_config("default")

    assert config.cooldown_ms == 30_000
    assert config.probe_interval_ms == 30_000


def test_get_preset_config_aggressive():
    """Test getting aggressive preset config."""
    config = get_preset_config("aggressive")

    assert config.cooldown_ms == 15_000
    assert config.probe_interval_ms == 10_000
    assert config.max_probe_attempts == 5


def test_get_preset_config_conservative():
    """Test getting conservative preset config."""
    config = get_preset_config("conservative")

    assert config.cooldown_ms == 120_000
    assert config.probe_interval_ms == 60_000
    assert config.max_probe_attempts == 2


def test_get_preset_config_unknown():
    """Test getting unknown preset raises error."""
    with pytest.raises(ValueError, match="Unknown preset"):
        get_preset_config("nonexistent")


def test_preset_configs_available():
    """Test that all preset configs are accessible."""
    assert "default" in PRESET_CONFIGS
    assert "aggressive" in PRESET_CONFIGS
    assert "conservative" in PRESET_CONFIGS
    assert "balanced" in PRESET_CONFIGS
    assert len(PRESET_CONFIGS) == 4
