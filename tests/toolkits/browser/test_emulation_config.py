"""Tests for EmulationConfig."""

import pytest

from myrm_agent_harness.toolkits.browser.pool.emulation import EmulationConfig


class TestEmulationConfigValidation:
    """Test EmulationConfig parameter validation."""

    def test_valid_geolocation(self) -> None:
        """Valid geolocation coordinates should convert successfully."""
        config = EmulationConfig(geolocation=(39.9, 116.4))
        kwargs = config.to_playwright_kwargs()
        assert kwargs["geolocation"] == {"latitude": 39.9, "longitude": 116.4}

    def test_geolocation_latitude_out_of_range(self) -> None:
        """Latitude outside [-90, 90] should raise ValueError at creation."""
        with pytest.raises(ValueError, match="Latitude must be in"):
            EmulationConfig(geolocation=(100.0, 0.0))

    def test_geolocation_longitude_out_of_range(self) -> None:
        """Longitude outside [-180, 180] should raise ValueError at creation."""
        with pytest.raises(ValueError, match="Longitude must be in"):
            EmulationConfig(geolocation=(0.0, 200.0))

    def test_timezone_conversion(self) -> None:
        """Timezone should convert to timezone_id."""
        config = EmulationConfig(timezone="Asia/Shanghai")
        kwargs = config.to_playwright_kwargs()
        assert kwargs["timezone_id"] == "Asia/Shanghai"

    def test_locale_conversion(self) -> None:
        """Locale should pass through unchanged."""
        config = EmulationConfig(locale="zh-CN")
        kwargs = config.to_playwright_kwargs()
        assert kwargs["locale"] == "zh-CN"

    def test_permissions_conversion(self) -> None:
        """Permissions tuple should convert to list for Playwright."""
        config = EmulationConfig(permissions=("geolocation", "notifications"))
        kwargs = config.to_playwright_kwargs()
        assert kwargs["permissions"] == ["geolocation", "notifications"]

    def test_color_scheme_conversion(self) -> None:
        """Color scheme should pass through unchanged."""
        config = EmulationConfig(color_scheme="dark")
        kwargs = config.to_playwright_kwargs()
        assert kwargs["color_scheme"] == "dark"

    def test_offline_mode(self) -> None:
        """Offline=True should be included in kwargs."""
        config = EmulationConfig(offline=True)
        kwargs = config.to_playwright_kwargs()
        assert kwargs["offline"] is True

    def test_offline_false_excluded(self) -> None:
        """Offline=False should not be included in kwargs."""
        config = EmulationConfig(offline=False)
        kwargs = config.to_playwright_kwargs()
        assert "offline" not in kwargs

    def test_empty_config(self) -> None:
        """Empty config should return empty dict."""
        config = EmulationConfig()
        kwargs = config.to_playwright_kwargs()
        assert kwargs == {}

    def test_full_config(self) -> None:
        """Full config with all fields should convert correctly."""
        config = EmulationConfig(
            geolocation=(39.9, 116.4),
            timezone="Asia/Shanghai",
            locale="zh-CN",
            permissions=("geolocation", "notifications"),
            color_scheme="dark",
            offline=True,
        )
        kwargs = config.to_playwright_kwargs()
        assert kwargs == {
            "geolocation": {"latitude": 39.9, "longitude": 116.4},
            "timezone_id": "Asia/Shanghai",
            "locale": "zh-CN",
            "permissions": ["geolocation", "notifications"],
            "color_scheme": "dark",
            "offline": True,
        }


class TestEmulationConfigExamples:
    """Test real-world usage examples."""

    def test_mobile_device_china(self) -> None:
        """Mobile device in China scenario."""
        config = EmulationConfig(
            geolocation=(39.9, 116.4),
            timezone="Asia/Shanghai",
            locale="zh-CN",
        )
        kwargs = config.to_playwright_kwargs()
        assert "geolocation" in kwargs
        assert "timezone_id" in kwargs
        assert "locale" in kwargs

    def test_dark_mode_testing(self) -> None:
        """Dark mode testing scenario."""
        config = EmulationConfig(color_scheme="dark")
        kwargs = config.to_playwright_kwargs()
        assert kwargs["color_scheme"] == "dark"

    def test_offline_testing(self) -> None:
        """Offline mode testing scenario."""
        config = EmulationConfig(offline=True)
        kwargs = config.to_playwright_kwargs()
        assert kwargs["offline"] is True

    def test_permission_testing(self) -> None:
        """Permission grant testing scenario."""
        config = EmulationConfig(
            geolocation=(37.7749, -122.4194),
            permissions=("geolocation",),
        )
        kwargs = config.to_playwright_kwargs()
        assert "geolocation" in kwargs
        assert "permissions" in kwargs


class TestEmulationConfigImmutability:
    """Test EmulationConfig immutability (frozen dataclass)."""

    def test_frozen_prevents_modification(self) -> None:
        """Frozen dataclass should prevent field modification."""
        from dataclasses import FrozenInstanceError

        config = EmulationConfig(geolocation=(31.2, 121.5))

        with pytest.raises(FrozenInstanceError):
            config.geolocation = (91, 0)

    def test_frozen_prevents_validation_bypass(self) -> None:
        """Frozen dataclass prevents setting invalid values after creation."""
        from dataclasses import FrozenInstanceError

        config = EmulationConfig(geolocation=(31.2, 121.5))

        with pytest.raises(FrozenInstanceError):
            config.geolocation = (91, 0)

        kwargs = config.to_playwright_kwargs()
        assert kwargs["geolocation"]["latitude"] == 31.2

    def test_hashable_for_caching(self) -> None:
        """Frozen dataclass is hashable and can be used in sets/dicts."""
        config1 = EmulationConfig(geolocation=(31.2, 121.5))
        config2 = EmulationConfig(geolocation=(31.2, 121.5))
        config3 = EmulationConfig(geolocation=(39.9, 116.4))

        cache = {config1: "result1", config2: "result2", config3: "result3"}
        assert len(cache) == 2
        assert cache[config1] == "result2"

    def test_empty_permissions_tuple(self) -> None:
        """Empty permissions tuple should convert to empty list."""
        config = EmulationConfig(permissions=())
        kwargs = config.to_playwright_kwargs()
        assert kwargs["permissions"] == []

    def test_edge_case_boundary_coordinates(self) -> None:
        """Test boundary coordinates (min/max valid values)."""
        config_min = EmulationConfig(geolocation=(-90, -180))
        kwargs_min = config_min.to_playwright_kwargs()
        assert kwargs_min["geolocation"] == {"latitude": -90, "longitude": -180}

        config_max = EmulationConfig(geolocation=(90, 180))
        kwargs_max = config_max.to_playwright_kwargs()
        assert kwargs_max["geolocation"] == {"latitude": 90, "longitude": 180}

    def test_edge_case_zero_coordinates(self) -> None:
        """Test zero coordinates (valid edge case)."""
        config = EmulationConfig(geolocation=(0, 0))
        kwargs = config.to_playwright_kwargs()
        assert kwargs["geolocation"] == {"latitude": 0, "longitude": 0}

    def test_field_defaults(self) -> None:
        """Test all field default values for coverage."""
        config = EmulationConfig()
        assert config.geolocation is None
        assert config.timezone is None
        assert config.locale is None
        assert config.permissions is None
        assert config.color_scheme is None
        assert config.offline is False
