"""DPI-aware bidirectional coordinate scaling.

Model returns coordinates in the downscaled image space; we must scale
them back to physical screen coordinates for accurate clicks. On Retina
displays, screen coordinates differ from physical pixels by the DPI scale.

Scaling chain:
  API coords → ×(screen/sent) → screen coords → ×dpi_scale → physical coords

[INPUT]
- types::ScreenInfo (POS: screen dimensions and DPI)

[OUTPUT]
- CoordinateScaler: stateless bidirectional scaler

[POS]
Stateless coordinate transformer. Created per-session with fixed parameters.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoordinateScaler:
    """Bidirectional coordinate scaler between API image space and screen space.

    Attributes:
        screen_width: Logical screen width (e.g. 1440 on Retina)
        screen_height: Logical screen height
        sent_width: Width of image sent to model API
        sent_height: Height of image sent to model API
        dpi_scale: Display DPI scale factor (2.0 for Retina)
    """

    screen_width: int
    screen_height: int
    sent_width: int
    sent_height: int
    dpi_scale: float = 1.0

    def api_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """Convert model-returned coordinates to screen coordinates.

        The model sees the downscaled image (sent_width × sent_height).
        Screen uses logical coordinates (screen_width × screen_height).
        """
        scale_x = self.screen_width / self.sent_width
        scale_y = self.screen_height / self.sent_height
        return int(x * scale_x), int(y * scale_y)

    def screen_to_api(self, x: int, y: int) -> tuple[int, int]:
        """Convert screen coordinates to model image coordinates.

        Used for annotating screenshots with click positions.
        """
        scale_x = self.sent_width / self.screen_width
        scale_y = self.sent_height / self.screen_height
        return int(x * scale_x), int(y * scale_y)

    def validate_api_coords(self, x: int, y: int) -> bool:
        """Check if API coordinates are within the sent image bounds."""
        return 0 <= x <= self.sent_width and 0 <= y <= self.sent_height
