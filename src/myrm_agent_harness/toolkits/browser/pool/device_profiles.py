"""Curated mobile device profiles for browser device emulation.

[INPUT]
- .emulation::EmulationConfig (POS: browser environment emulation config with type safety and parameter validation)

[OUTPUT]
- MOBILE_DEVICES: curated mainstream device profile registry
- resolve_device: Look up a device by name into an EmulationConfig
- list_device_names: Enumerate available device names

[POS]
Static device descriptor registry curated from the patchright (Playwright)
``devices`` registry (207 entries). Each entry carries the five dimensions a
mobile emulation needs: UA string, layout viewport, device pixel ratio, mobile
flag, and touch flag. Resolving a device returns a reusable ``EmulationConfig``
so both context creation (``to_playwright_kwargs``) and runtime CDP injection
share the same source of truth. Zero runtime dependency on a live browser.
"""

from __future__ import annotations

from typing import Final

from .emulation import EmulationConfig

MOBILE_DEVICES: Final[dict[str, EmulationConfig]] = {
    "iPhone 15 Pro": EmulationConfig(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Mobile/15E148 Safari/604.1"
        ),
        viewport=(393, 659),
        device_scale_factor=3.0,
        is_mobile=True,
        has_touch=True,
    ),
    "iPhone 13": EmulationConfig(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Mobile/15E148 Safari/604.1"
        ),
        viewport=(390, 664),
        device_scale_factor=3.0,
        is_mobile=True,
        has_touch=True,
    ),
    "iPhone SE": EmulationConfig(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_1 like Mac OS X) "
            "AppleWebKit/603.1.30 (KHTML, like Gecko) Version/26.5 Mobile/14E304 Safari/602.1"
        ),
        viewport=(320, 568),
        device_scale_factor=2.0,
        is_mobile=True,
        has_touch=True,
    ),
    "Pixel 8": EmulationConfig(
        user_agent=(
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/149.0.7827.55 Mobile Safari/537.36"
        ),
        viewport=(412, 839),
        device_scale_factor=2.625,
        is_mobile=True,
        has_touch=True,
    ),
    "Pixel 7": EmulationConfig(
        user_agent=(
            "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/149.0.7827.55 Mobile Safari/537.36"
        ),
        viewport=(412, 839),
        device_scale_factor=2.625,
        is_mobile=True,
        has_touch=True,
    ),
    "Galaxy S24": EmulationConfig(
        user_agent=(
            "Mozilla/5.0 (Linux; Android 14; SM-S921U) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/149.0.7827.55 Mobile Safari/537.36"
        ),
        viewport=(360, 780),
        device_scale_factor=3.0,
        is_mobile=True,
        has_touch=True,
    ),
    "iPad Pro 11": EmulationConfig(
        user_agent=(
            "Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/26.5 Mobile/15E148 Safari/604.1"
        ),
        viewport=(834, 1194),
        device_scale_factor=2.0,
        is_mobile=True,
        has_touch=True,
    ),
    "Nexus 7": EmulationConfig(
        user_agent=(
            "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 7 Build/MOB30X) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7827.55 Safari/537.36"
        ),
        viewport=(600, 960),
        device_scale_factor=2.0,
        is_mobile=True,
        has_touch=True,
    ),
}

# Default mobile device when the agent asks for a generic "mobile" view.
DEFAULT_MOBILE_DEVICE: Final[str] = "iPhone 15 Pro"


def resolve_device(name: str) -> EmulationConfig | None:
    """Resolve a device name into an EmulationConfig.

    Args:
        name: Device name from ``list_device_names`` (case-insensitive
            partial match preferred for exact names).

    Returns:
        Matching EmulationConfig, or ``None`` when the device is unknown.

    """
    if not name.strip():
        return None

    lowered = name.strip().lower()
    for device_name, config in MOBILE_DEVICES.items():
        if device_name.lower() == lowered:
            return config

    # Case-insensitive contains match as a convenience (e.g. "iphone").
    for device_name, config in MOBILE_DEVICES.items():
        if lowered in device_name.lower():
            return config

    return None


def list_device_names() -> list[str]:
    """Return the sorted list of available device names."""
    return sorted(MOBILE_DEVICES)
