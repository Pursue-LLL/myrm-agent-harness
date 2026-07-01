"""Type definitions for computer use toolkit.

[INPUT]
- (none)

[OUTPUT]
- ComputerAction, DesktopInteractAction, DesktopVisionAction, ScrollDirection, ModifierKey, ScreenInfo, ScreenContext, ActionResult, WindowTextResult, ImageConstraints, PermissionStatus, ExecutionMode, ForegroundPermissionScope, ForegroundPermissionResult, ForegroundPermissionCallback, ComputerUseConfig

[POS]
Shared type definitions consumed by all computer_use submodules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol

DesktopInteractAction = Literal[
    "click",
    "dblclick",
    "fill",
    "type",
    "fill_credential",
    "press",
    "hover",
    "focus",
    "scroll",
]

DesktopVisionAction = Literal[
    "capture",
    "screenshot",
    "left_click",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
    "type",
    "key",
    "scroll",
    "drag",
    "mouse_move",
    "wait",
]

ComputerAction = Literal[
    "left_click",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
    "mouse_move",
    "left_click_drag",
    "scroll",
    "key",
    "type",
    "screenshot",
    "wait",
]

ScrollDirection = Literal["up", "down", "left", "right"]

ModifierKey = Literal["ctrl", "shift", "alt", "meta"]


@dataclass(frozen=True)
class ScreenInfo:
    """Physical screen dimensions and DPI information."""

    width: int
    height: int
    dpi_scale: float = 1.0

    @property
    def physical_width(self) -> int:
        return int(self.width * self.dpi_scale)

    @property
    def physical_height(self) -> int:
        return int(self.height * self.dpi_scale)


@dataclass
class ActionResult:
    """Result of a computer action execution."""

    success: bool
    output: str = ""
    error: str = ""
    screenshot_base64: str = ""
    screenshot_size: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class ScreenContext:
    """Contextual state at time of screenshot (active window, mouse position)."""

    active_window: str = ""
    mouse_x: int = 0
    mouse_y: int = 0


@dataclass(frozen=True)
class WindowTextResult:
    """Result of extracting text from the frontmost window via Accessibility API."""

    window_title: str = ""
    app_name: str = ""
    text: str = ""
    success: bool = True
    needs_permission: bool = False


@dataclass(frozen=True)
class ImageConstraints:
    """Vision encoder constraints for a specific model family.

    Anthropic Claude: max_edge=1568, max_tokens=1568, px_per_token=28
    OpenAI GPT-4V: max_edge=2048, max_tokens=2048, px_per_token=32
    """

    max_edge_px: int = 1568
    max_tokens: int = 1568
    px_per_token: int = 28
    jpeg_quality: int = 75
    min_screenshot_bytes: int = 1024


CLAUDE_IMAGE_CONSTRAINTS = ImageConstraints(
    max_edge_px=1568,
    max_tokens=1568,
    px_per_token=28,
)

CLAUDE_OPUS_47_IMAGE_CONSTRAINTS = ImageConstraints(
    max_edge_px=2576,
    max_tokens=3750,
    px_per_token=28,
)

GPT4V_IMAGE_CONSTRAINTS = ImageConstraints(
    max_edge_px=2048,
    max_tokens=2048,
    px_per_token=32,
)

DEFAULT_IMAGE_CONSTRAINTS = CLAUDE_IMAGE_CONSTRAINTS


KNOWN_BROWSER_NAMES = frozenset(
    {
        "google chrome",
        "chromium",
        "firefox",
        "safari",
        "microsoft edge",
        "brave browser",
        "arc",
        "patchright",
        "camoufox",
        "google-chrome",
        "microsoft-edge",
        "brave",
    }
)


@dataclass(frozen=True)
class PermissionStatus:
    """OS-level permission status for desktop automation.

    Each field indicates whether the corresponding permission is granted.
    ``settings_deeplinks`` maps permission names to OS Settings URLs.
    """

    accessibility: bool = True
    screen_recording: bool = True
    platform: str = ""
    settings_deeplinks: dict[str, str] = field(default_factory=dict)

    @property
    def all_granted(self) -> bool:
        return self.accessibility and self.screen_recording


class ExecutionMode(Enum):
    """Controls how the computer use session handles foreground-stealing operations.

    - background_strict: Never steal foreground without explicit user permission.
      If permission is denied or callback is unavailable, the operation fails gracefully.
    - background_best_effort: Attempt background execution; if unavailable, request
      permission before falling back to foreground.
    - foreground: Execute all operations directly (legacy behavior, no permission checks).
    """

    background_strict = "background_strict"
    background_best_effort = "background_best_effort"
    foreground = "foreground"


class ForegroundPermissionScope(Enum):
    """Scope of a foreground permission grant (modeled after iOS permission UX)."""

    once = "once"
    session = "session"
    always = "always"


@dataclass(frozen=True)
class ForegroundPermissionResult:
    """Result returned by the permission callback."""

    granted: bool
    scope: ForegroundPermissionScope = ForegroundPermissionScope.once


class ForegroundPermissionCallback(Protocol):
    """Protocol that server/frontend must implement to show a permission prompt.

    The harness calls this when it needs to steal foreground focus. The implementation
    should present a UI prompt (WebSocket push, Tauri dialog, etc.) and return the
    user's decision. For cloud-hosted sandboxes, implement as auto-grant.
    """

    async def __call__(
        self,
        *,
        reason: str,
        operation: str,
        estimated_duration_seconds: float,
        timeout_seconds: float = 30.0,
    ) -> ForegroundPermissionResult:
        """Request foreground permission from the user.

        Args:
            reason: Human-readable explanation of why foreground is needed.
            operation: The specific action being attempted (e.g. "click at (320, 480)").
            estimated_duration_seconds: How long the foreground operation will take.
            timeout_seconds: Max time to wait for user response before auto-denying.
        """
        ...


@dataclass
class ComputerUseConfig:
    """Configuration for computer use session."""

    image_constraints: ImageConstraints = field(default_factory=lambda: DEFAULT_IMAGE_CONSTRAINTS)
    screenshot_delay: float = 1.0
    typing_delay_ms: int = 12
    typing_chunk_size: int = 50
    execution_mode: ExecutionMode = ExecutionMode.background_best_effort
