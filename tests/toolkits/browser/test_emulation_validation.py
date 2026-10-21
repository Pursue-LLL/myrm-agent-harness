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


class TestEmulationConfigDeviceValidation:
    """Tests for mobile device dimension validation"""

    def test_viewport_too_small_raises(self):
        """Test non-positive viewport raises ValueError"""
        with pytest.raises(ValueError, match="Viewport dimensions must be positive"):
            EmulationConfig(viewport=(0, 800))
        with pytest.raises(ValueError, match="Viewport dimensions must be positive"):
            EmulationConfig(viewport=(390, -1))

    def test_viewport_valid(self):
        """Test valid viewport is accepted"""
        config = EmulationConfig(viewport=(393, 659))
        assert config.viewport == (393, 659)

    def test_device_scale_factor_non_positive_raises(self):
        """Test non-positive device_scale_factor raises ValueError"""
        with pytest.raises(ValueError, match="device_scale_factor must be positive"):
            EmulationConfig(device_scale_factor=0.0)
        with pytest.raises(ValueError, match="device_scale_factor must be positive"):
            EmulationConfig(device_scale_factor=-2.0)

    def test_device_scale_factor_valid(self):
        """Test valid device_scale_factor is accepted"""
        config = EmulationConfig(device_scale_factor=3.0)
        assert config.device_scale_factor == 3.0

    def test_device_fields_to_playwright_kwargs(self):
        """Test mobile device fields convert to Playwright kwargs"""
        config = EmulationConfig(
            viewport=(393, 659),
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X)",
            device_scale_factor=3.0,
            is_mobile=True,
            has_touch=True,
        )
        kwargs = config.to_playwright_kwargs()
        assert kwargs["viewport"] == {"width": 393, "height": 659}
        assert kwargs["user_agent"].startswith("Mozilla/5.0")
        assert kwargs["device_scale_factor"] == 3.0
        assert kwargs["is_mobile"] is True
        assert kwargs["has_touch"] is True

    def test_empty_device_fields_not_in_kwargs(self):
        """Test unset device fields do not leak into kwargs"""
        config = EmulationConfig()
        kwargs = config.to_playwright_kwargs()
        assert "viewport" not in kwargs
        assert "user_agent" not in kwargs
        assert "device_scale_factor" not in kwargs
        assert "is_mobile" not in kwargs
        assert "has_touch" not in kwargs
