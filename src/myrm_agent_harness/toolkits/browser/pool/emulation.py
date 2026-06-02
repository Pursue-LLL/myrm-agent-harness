"""Browser environment emulation configuration.


[INPUT]
- typing::Literal (POS: type hints for restricted values)

[OUTPUT]
- EmulationConfig: Type-safe configuration for browser environment emulation

[POS]
Browser environment emulation configuration with type safety and parameter validation.
Provides dataclass-based configuration for geolocation, timezone, locale, permissions,
color scheme, and offline mode. Converts to Playwright new_context parameters.
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

        return kwargs
