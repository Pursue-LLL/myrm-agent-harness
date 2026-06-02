"""Complete validation tests for config module"""

import pytest

from myrm_agent_harness.toolkits.browser.pool.config import (
    BrowserMode,
    BrowserPoolConfig,
    CircuitBreakerConfig,
)
from myrm_agent_harness.toolkits.browser.pool.emulation import EmulationConfig


class TestCircuitBreakerConfigValidation:
    """Tests for CircuitBreakerConfig validation"""

    def test_validation_failure_threshold_zero(self):
        """Test failure_threshold=0 raises ValueError"""
        with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
            CircuitBreakerConfig(failure_threshold=0)

    def test_validation_failure_threshold_negative(self):
        """Test negative failure_threshold raises ValueError"""
        with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
            CircuitBreakerConfig(failure_threshold=-1)

    def test_validation_timeout_zero(self):
        """Test timeout=0 raises ValueError"""
        with pytest.raises(ValueError, match="timeout must be > 0"):
            CircuitBreakerConfig(timeout=0.0)

    def test_validation_timeout_negative(self):
        """Test negative timeout raises ValueError"""
        with pytest.raises(ValueError, match="timeout must be > 0"):
            CircuitBreakerConfig(timeout=-10.0)


class TestBrowserPoolConfigPresets:
    """Tests for BrowserPoolConfig preset methods"""

    def test_defensive_preset(self):
        """Test defensive preset returns correct config"""
        config = BrowserPoolConfig.defensive()

        assert config.max_concurrent_pages == 50
        assert config.rate_limiter.mode.value == "domain"
        assert config.rate_limiter.domain_qps == 5.0
        assert config.circuit_breaker.enabled is True
        assert config.circuit_breaker.failure_threshold == 3
        assert config.circuit_breaker.timeout == 30.0
        assert config.memory_guard.enabled is True
        assert config.memory_guard.max_memory_percent == 85.0

    def test_minimal_preset(self):
        """Test minimal preset returns correct config"""
        config = BrowserPoolConfig.minimal()

        assert config.max_concurrent_pages == 10
        assert config.rate_limiter.mode.value == "none"
        assert config.circuit_breaker.enabled is False
        assert config.memory_guard.enabled is False


class TestDefaultEmulation:
    """Tests for BrowserConfig.default_emulation integration with BrowserMode."""

    _CLIPBOARD_PERMS = ("clipboard-read", "clipboard-write")

    def test_standard_has_clipboard_permissions(self):
        config = BrowserPoolConfig.standard()
        assert config.default_emulation is not None
        assert config.default_emulation.permissions == self._CLIPBOARD_PERMS

    def test_defensive_has_clipboard_permissions(self):
        config = BrowserPoolConfig.defensive()
        assert config.default_emulation is not None
        assert config.default_emulation.permissions == self._CLIPBOARD_PERMS

    def test_minimal_has_no_default_emulation(self):
        config = BrowserPoolConfig.minimal()
        assert config.default_emulation is None

    def test_default_constructor_uses_standard_mode(self):
        config = BrowserPoolConfig()
        assert config.mode == BrowserMode.STANDARD
        assert config.default_emulation is not None
        assert config.default_emulation.permissions == self._CLIPBOARD_PERMS

    def test_post_init_auto_fills_when_none(self):
        config = BrowserPoolConfig(mode=BrowserMode.STANDARD, default_emulation=None)
        assert config.default_emulation is not None
        assert config.default_emulation.permissions == self._CLIPBOARD_PERMS

    def test_explicit_emulation_preserved(self):
        custom = EmulationConfig(permissions=("geolocation", "notifications"))
        config = BrowserPoolConfig(default_emulation=custom)
        assert config.default_emulation is custom
        assert config.default_emulation.permissions == ("geolocation", "notifications")

    def test_with_mode_updates_emulation(self):
        std = BrowserPoolConfig.standard()
        mini = std.with_mode(BrowserMode.MINIMAL)
        assert mini.default_emulation is None

        back_to_std = mini.with_mode(BrowserMode.STANDARD)
        assert back_to_std.default_emulation is not None
        assert back_to_std.default_emulation.permissions == self._CLIPBOARD_PERMS

    def test_with_mode_defensive(self):
        std = BrowserPoolConfig.standard()
        dfn = std.with_mode(BrowserMode.DEFENSIVE)
        assert dfn.default_emulation is not None
        assert dfn.default_emulation.permissions == self._CLIPBOARD_PERMS

    def test_emulation_is_frozen(self):
        config = BrowserPoolConfig.standard()
        assert config.default_emulation is not None
        with pytest.raises(AttributeError):
            config.default_emulation.permissions = ("geolocation",)  # type: ignore[misc]

    def test_emulation_to_playwright_kwargs(self):
        config = BrowserPoolConfig.standard()
        assert config.default_emulation is not None
        kwargs = config.default_emulation.to_playwright_kwargs()
        assert kwargs == {"permissions": ["clipboard-read", "clipboard-write"]}
