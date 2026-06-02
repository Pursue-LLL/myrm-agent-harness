"""Tests for EmulationConfig validation"""

import pytest

from myrm_agent_harness.toolkits.browser.pool.emulation import EmulationConfig


class TestEmulationConfigGeolocationValidation:
    """Tests for geolocation coordinate validation"""

    def test_validation_latitude_too_high(self):
        """Test latitude > 90 raises ValueError"""
        with pytest.raises(ValueError, match="Latitude must be in"):
            EmulationConfig(geolocation=(91.0, 0.0))

    def test_validation_latitude_too_low(self):
        """Test latitude < -90 raises ValueError"""
        with pytest.raises(ValueError, match="Latitude must be in"):
            EmulationConfig(geolocation=(-91.0, 0.0))

    def test_validation_longitude_too_high(self):
        """Test longitude > 180 raises ValueError"""
        with pytest.raises(ValueError, match="Longitude must be in"):
            EmulationConfig(geolocation=(0.0, 181.0))

    def test_validation_longitude_too_low(self):
        """Test longitude < -180 raises ValueError"""
        with pytest.raises(ValueError, match="Longitude must be in"):
            EmulationConfig(geolocation=(0.0, -181.0))

    def test_validation_valid_geolocation(self):
        """Test valid geolocation coordinates"""
        config = EmulationConfig(geolocation=(37.7749, -122.4194))
        assert config.geolocation == (37.7749, -122.4194)


class TestEmulationConfigToPlaywrightKwargs:
    """Tests for to_playwright_kwargs conversion"""

    def test_offline_mode_conversion(self):
        """测试：offline=True 正确转换为 kwargs"""
        config = EmulationConfig(offline=True)
        kwargs = config.to_playwright_kwargs()
        assert kwargs["offline"] is True

    def test_offline_false_not_in_kwargs(self):
        """测试：offline=False 不添加到 kwargs"""
        config = EmulationConfig(offline=False)
        kwargs = config.to_playwright_kwargs()
        assert "offline" not in kwargs
