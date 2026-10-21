"""Unit tests for pool configuration modules"""

import dataclasses

import pytest

from myrm_agent_harness.toolkits.browser.pool.config import (
    _DEFAULT_CDP_ENDPOINT,
    BrowserConfig,
    BrowserMode,
    LaunchMode,
    RateLimiterConfig,
    ResourceBlockConfig,
    RobustnessPolicy,
    ThrottleMode,
)


class TestRateLimiterConfig:
    """RateLimiterConfig tests"""

    def test_default_config(self):
        """Test default configuration"""
        config = RateLimiterConfig()

        assert config.mode == ThrottleMode.NONE
        assert config.domain_qps == 5.0
        assert config.domain_burst == 10


class TestBrowserConfig:
    """BrowserConfig tests"""

    def test_default_config(self):
        """Test default configuration"""
        config = BrowserConfig()

        assert config.mode == BrowserMode.STANDARD
        assert config.max_concurrent_pages == 30
        assert isinstance(config.resource_block, type(config.resource_block))

    def test_mode_driven_rate_limiter(self):
        """Test rate limiter is driven by mode"""
        minimal = BrowserConfig.minimal()
        assert minimal.rate_limiter.mode == ThrottleMode.NONE

        standard = BrowserConfig.standard()
        assert standard.rate_limiter.mode == ThrottleMode.DOMAIN

        defensive = BrowserConfig.defensive()
        assert defensive.rate_limiter.mode == ThrottleMode.DOMAIN

    def test_mode_driven_circuit_breaker(self):
        """Test circuit breaker is driven by mode"""
        minimal = BrowserConfig.minimal()
        assert minimal.circuit_breaker.enabled is False

        standard = BrowserConfig.standard()
        assert standard.circuit_breaker.enabled is False

        defensive = BrowserConfig.defensive()
        assert defensive.circuit_breaker.enabled is True

    def test_mode_driven_memory_guard(self):
        """Test memory guard is driven by mode"""
        assert BrowserConfig.minimal().memory_guard.enabled is False
        assert BrowserConfig.standard().memory_guard.enabled is False
        assert BrowserConfig.defensive().memory_guard.enabled is True

    def test_validation_invalid_max_concurrent_pages_low(self):
        """Test invalid max_concurrent_pages (too low) raises ValueError"""
        with pytest.raises(ValueError, match="max_concurrent_pages must be in"):
            BrowserConfig(max_concurrent_pages=0)

    def test_validation_invalid_max_concurrent_pages_high(self):
        """Test invalid max_concurrent_pages (too high) raises ValueError"""
        with pytest.raises(ValueError, match="max_concurrent_pages must be in"):
            BrowserConfig(max_concurrent_pages=150)

    def test_from_mode_covers_every_browser_mode(self) -> None:
        """Every BrowserMode enum member must be listed in _MODE_BLUEPRINTS (from_mode must not fail)."""
        for mode in BrowserMode:
            RobustnessPolicy.from_mode(mode)

    def test_explicit_robustness_mismatching_mode_raises(self) -> None:
        """Structural mismatch between mode and robustness is rejected."""
        with pytest.raises(ValueError, match="structurally compatible"):
            BrowserConfig(
                mode=BrowserMode.MINIMAL,
                max_concurrent_pages=10,
                resource_block=ResourceBlockConfig(),
                robustness=RobustnessPolicy.from_mode(BrowserMode.DEFENSIVE),
            )

    def test_with_mode_updates_robustness_preserves_pages_and_resource_block(self) -> None:
        """with_mode switches mode and default robustness; keeps pages and resource_block."""
        base = BrowserConfig.standard()
        switched = base.with_mode(BrowserMode.MINIMAL)
        assert switched.mode == BrowserMode.MINIMAL
        assert switched.max_concurrent_pages == base.max_concurrent_pages
        assert switched.resource_block is base.resource_block
        assert switched.robustness == RobustnessPolicy.from_mode(BrowserMode.MINIMAL)

    def test_dataclasses_replace_memory_tuning_keeps_defensive_shape(self) -> None:
        """Tuning numeric fields under DEFENSIVE keeps structural compatibility."""
        base = BrowserConfig.defensive()
        new_mg = dataclasses.replace(base.memory_guard, max_memory_percent=95.0)
        cfg = dataclasses.replace(
            base,
            robustness=dataclasses.replace(base.robustness, memory_guard=new_mg),
        )
        assert cfg.mode == BrowserMode.DEFENSIVE
        assert cfg.memory_guard.max_memory_percent == 95.0

    def test_dataclasses_replace_mode_only_without_new_robustness_raises(self) -> None:
        """Changing mode via replace without updating robustness is invalid."""
        base = BrowserConfig.defensive()
        with pytest.raises(ValueError, match="structurally compatible"):
            dataclasses.replace(base, mode=BrowserMode.MINIMAL)


class TestRobustnessPolicy:
    """RobustnessPolicy factory tests."""

    def test_from_mode_minimal(self) -> None:
        policy = RobustnessPolicy.from_mode(BrowserMode.MINIMAL)
        assert policy.rate_limiter.mode == ThrottleMode.NONE
        assert policy.memory_guard.enabled is False
        assert policy.circuit_breaker.enabled is False

    def test_from_mode_standard(self) -> None:
        policy = RobustnessPolicy.from_mode(BrowserMode.STANDARD)
        assert policy.rate_limiter.mode == ThrottleMode.DOMAIN
        assert policy.rate_limiter.domain_qps == 5.0
        assert policy.memory_guard.enabled is False
        assert policy.circuit_breaker.enabled is False

    def test_from_mode_defensive(self) -> None:
        policy = RobustnessPolicy.from_mode(BrowserMode.DEFENSIVE)
        assert policy.rate_limiter.mode == ThrottleMode.DOMAIN
        assert policy.memory_guard.enabled is True
        assert policy.circuit_breaker.enabled is True


class TestLaunchMode:
    """LaunchMode enum and BrowserConfig integration tests."""

    def test_enum_values(self) -> None:
        assert LaunchMode.LAUNCH == "launch"
        assert LaunchMode.CONNECT == "connect"
        assert LaunchMode.AUTO == "auto"

    def test_default_launch_mode_is_launch(self) -> None:
        config = BrowserConfig()
        assert config.launch_mode == LaunchMode.LAUNCH

    def test_default_cdp_endpoint_is_none(self) -> None:
        config = BrowserConfig()
        assert config.cdp_endpoint is None

    def test_presets_default_to_launch_mode(self) -> None:
        assert BrowserConfig.minimal().launch_mode == LaunchMode.LAUNCH
        assert BrowserConfig.standard().launch_mode == LaunchMode.LAUNCH
        assert BrowserConfig.defensive().launch_mode == LaunchMode.LAUNCH

    def test_replace_launch_mode(self) -> None:
        base = BrowserConfig.minimal()
        cfg = dataclasses.replace(base, launch_mode=LaunchMode.AUTO, cdp_endpoint="http://127.0.0.1:9333")
        assert cfg.launch_mode == LaunchMode.AUTO
        assert cfg.cdp_endpoint == "http://127.0.0.1:9333"
        assert cfg.mode == BrowserMode.MINIMAL

    def test_with_mode_preserves_launch_mode(self) -> None:
        base = dataclasses.replace(BrowserConfig.standard(), launch_mode=LaunchMode.AUTO)
        switched = base.with_mode(BrowserMode.DEFENSIVE)
        assert switched.launch_mode == LaunchMode.AUTO
        assert switched.mode == BrowserMode.DEFENSIVE

    def test_default_cdp_endpoint_constant(self) -> None:
        assert _DEFAULT_CDP_ENDPOINT == "http://127.0.0.1:9222"


class TestThrottleMode:
    """ThrottleMode enum tests"""

    def test_enum_values(self):
        """Test enum values"""
        assert ThrottleMode.NONE == "none"
        assert ThrottleMode.DOMAIN == "domain"

    def test_enum_membership(self):
        """Test enum membership"""
        assert "none" in [mode.value for mode in ThrottleMode]
        assert "domain" in [mode.value for mode in ThrottleMode]
