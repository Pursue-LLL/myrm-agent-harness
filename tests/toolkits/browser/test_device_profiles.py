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

    def test_resolve_all_entries_are_valid_configs(self) -> None:
        """Every registry entry is a fully-populated mobile config."""
        for name, config in MOBILE_DEVICES.items():
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
