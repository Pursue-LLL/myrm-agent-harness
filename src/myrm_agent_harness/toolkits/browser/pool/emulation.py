"""Browser environment emulation configuration.


[INPUT]
- typing::Literal (POS: type hints for restricted values)

[OUTPUT]
- EmulationConfig: Type-safe configuration for browser environment emulation

[POS]
Browser environment emulation configuration with type safety and parameter
validation. Covers geolocation/timezone/locale/permissions/color scheme/offline
plus mobile device dimensions (viewport/user_agent/device_scale_factor/is_mobile/
has_touch); converts to Playwright new_context parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class EmulationConfig:
    """Type-safe browser environment emulation configuration.

    Provides IDE autocomplete, type checking, and parameter validation for
    common browser emulation scenarios (geolocation, timezone, locale, etc.).

    Examples:
        # Mobile device in China
        EmulationConfig(
            geolocation=(39.9, 116.4),
            timezone="Asia/Shanghai",
            locale="zh-CN"
        )

        # Dark mode testing
        EmulationConfig(color_scheme="dark")

        # Offline mode
        EmulationConfig(offline=True)

        # Mobile device emulation (iPhone-class: 393x659 @3x, touch)
        EmulationConfig(
            viewport=(393, 659),
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X)",
            device_scale_factor=3.0,
            is_mobile=True,
            has_touch=True,
        )

    """

    geolocation: tuple[float, float] | None = None
    """Geographic location as (latitude, longitude).

    Latitude must be in [-90, 90], longitude in [-180, 180].
    Requires 'geolocation' in permissions list to work.
    """

    timezone: str | None = None
    """IANA timezone identifier (e.g., 'Asia/Shanghai', 'America/New_York')."""

    locale: str | None = None
    """BCP 47 language tag (e.g., 'zh-CN', 'en-US', 'ja-JP')."""

    permissions: tuple[str, ...] | None = None
    """Browser permissions to grant automatically.

    Common values: 'geolocation', 'notifications', 'camera', 'microphone',
    'clipboard-read', 'clipboard-write'.
    Use tuple for immutability (enables hashable dataclass).
    """

    color_scheme: Literal["light", "dark", "no-preference"] | None = None
    """Emulate 'prefers-color-scheme' media feature for dark mode testing."""

    offline: bool = False
    """Enable offline mode (network disconnected)."""

    viewport: tuple[int, int] | None = None
    """Viewport size as (width, height) in CSS pixels.

    When set together with ``is_mobile``, applies the device's layout viewport
    (e.g. iPhone 15 Pro: (393, 659)); otherwise overrides the desktop default.
    """

    user_agent: str | None = None
    """Mobile (or custom) User-Agent string sent by the browser context."""

    device_scale_factor: float | None = None
    """Device pixel ratio (e.g. 3.0 for iPhone, 2.625 for Pixel 8)."""

    is_mobile: bool | None = None
    """Whether the context emulates a mobile device (affects meta viewport handling)."""

    has_touch: bool | None = None
    """Whether the context emulates a touch screen (touch event support)."""

    def __post_init__(self) -> None:
        """Validate configuration parameters at creation time.

        Raises:
            ValueError: If geolocation coordinates are out of valid range

        """
        if self.geolocation is not None:
            lat, lon = self.geolocation
            if not (-90 <= lat <= 90):
                msg = f"Latitude must be in [-90, 90], got {lat}"
                raise ValueError(msg)
            if not (-180 <= lon <= 180):
                msg = f"Longitude must be in [-180, 180], got {lon}"
                raise ValueError(msg)

        if self.viewport is not None:
            width, height = self.viewport
            if width <= 0 or height <= 0:
                msg = f"Viewport dimensions must be positive, got {self.viewport}"
                raise ValueError(msg)

        if self.device_scale_factor is not None and self.device_scale_factor <= 0:
            msg = (
                "device_scale_factor must be positive, "
                f"got {self.device_scale_factor}"
            )
            raise ValueError(msg)

    def to_playwright_kwargs(self) -> dict[str, object]:
        """Convert to Playwright browser.new_context() parameters.

        Returns:
            Dictionary of Playwright context options

        """
        kwargs: dict[str, object] = {}

        if self.geolocation is not None:
            lat, lon = self.geolocation
            kwargs["geolocation"] = {"latitude": lat, "longitude": lon}

        if self.timezone is not None:
            kwargs["timezone_id"] = self.timezone

        if self.locale is not None:
            kwargs["locale"] = self.locale

        if self.permissions is not None:
            kwargs["permissions"] = list(self.permissions)

        if self.color_scheme is not None:
            kwargs["color_scheme"] = self.color_scheme

        if self.offline:
            kwargs["offline"] = True

        if self.viewport is not None:
            width, height = self.viewport
            kwargs["viewport"] = {"width": width, "height": height}

        if self.user_agent is not None:
            kwargs["user_agent"] = self.user_agent

        if self.device_scale_factor is not None:
            kwargs["device_scale_factor"] = self.device_scale_factor

        if self.is_mobile is not None:
            kwargs["is_mobile"] = self.is_mobile

        if self.has_touch is not None:
            kwargs["has_touch"] = self.has_touch

        return kwargs
