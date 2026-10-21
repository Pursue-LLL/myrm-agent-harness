"""Tests for the curated mobile device profile registry."""

from myrm_agent_harness.toolkits.browser.pool.device_profiles import (
    DEFAULT_MOBILE_DEVICE,
    MOBILE_DEVICES,
    list_device_names,
    resolve_device,
)


class TestResolveDevice:
    def test_resolve_exact_name_case_insensitive(self) -> None:
        """Exact device name resolves regardless of case."""
        config = resolve_device("iphone 15 pro")
        assert config is not None
        assert config.viewport == (393, 659)
        assert config.device_scale_factor == 3.0
        assert config.is_mobile is True
        assert config.has_touch is True
        assert "iPhone" in config.user_agent

    def test_resolve_partial_name(self) -> None:
        """Partial name matching resolves to a device."""
        assert resolve_device("pixel") is not None
        assert resolve_device("galaxy") is not None
        assert resolve_device("ipad") is not None

    def test_resolve_unknown_returns_none(self) -> None:
        """Unknown device names return None."""
        assert resolve_device("Nokia 3310") is None
        assert resolve_device("") is None
        assert resolve_device("   ") is None

    def test_resolve_landscape_swaps_viewport(self) -> None:
        """A ' landscape' suffix swaps the layout viewport to landscape."""
        portrait = resolve_device("iPhone 15 Pro")
        landscape = resolve_device("iPhone 15 Pro landscape")
        assert landscape is not None
        assert landscape.viewport == (659, 393)
        assert landscape.user_agent == portrait.user_agent
        assert landscape.device_scale_factor == portrait.device_scale_factor
        assert landscape.is_mobile is True
        assert landscape.has_touch is True

    def test_resolve_landscape_case_insensitive_and_partial(self) -> None:
        """Landscape suffix works with any casing and partial device names."""
        assert resolve_device("iphone 15 pro LANDSCAPE").viewport == (659, 393)
        assert resolve_device("Pixel landscape").viewport is not None
        assert resolve_device("landscape") is None

    def test_resolve_all_entries_are_valid_configs(self) -> None:
        """Every registry entry is a fully-populated mobile config."""
        for config in MOBILE_DEVICES.values():
            assert config.user_agent
            assert config.viewport is not None
            assert config.viewport[0] > 0 and config.viewport[1] > 0
            assert config.device_scale_factor is not None
            assert config.device_scale_factor > 0
            assert config.is_mobile is True
            assert config.has_touch is True


class TestListDeviceNames:
    def test_list_is_sorted(self) -> None:
        """Device names are returned sorted."""
        names = list_device_names()
        assert names == sorted(names)
        assert len(names) > 0

    def test_default_device_is_registered(self) -> None:
        """The default mobile device exists in the registry."""
        assert DEFAULT_MOBILE_DEVICE in list_device_names()
        assert resolve_device(DEFAULT_MOBILE_DEVICE) is not None
