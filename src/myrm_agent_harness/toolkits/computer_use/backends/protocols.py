"""ComputerBackend protocol — platform-agnostic contract for screen I/O.

[INPUT]
- types::ScreenInfo, ActionResult, WindowTextResult, PermissionStatus (POS: shared type definitions)

[OUTPUT]
- ComputerBackend: Protocol that platform backends must implement

[POS]
Dependency-inversion boundary between ComputerSession and platform-specific code.
"""

from __future__ import annotations

from typing import Protocol

from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ModifierKey,
    PermissionStatus,
    ScreenContext,
    ScreenInfo,
    WindowTextResult,
)


class ComputerBackend(Protocol):
    """Platform-agnostic contract for screen capture and input simulation."""

    async def screenshot(self) -> bytes:
        """Capture the primary screen as PNG bytes."""
        ...

    async def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        """Click at screen coordinates (x, y) with optional modifier keys held."""
        ...

    async def type_text(self, text: str, delay_ms: int = 12, chunk_size: int = 50) -> ActionResult:
        """Type text with optional keystroke delay."""
        ...

    async def type_credential(self, label: str) -> ActionResult:
        """Type a credential (password or TOTP) securely from the CredentialVault.

        The plain text is retrieved from the in-memory vault and injected directly
        via OS APIs without appearing in the LLM context or logs.
        """
        ...

    async def key(self, keys: str) -> ActionResult:
        """Press key combination (e.g. 'ctrl+c', 'Return')."""
        ...

    async def mouse_move(self, x: int, y: int) -> ActionResult:
        """Move mouse to screen coordinates."""
        ...

    async def scroll(
        self,
        x: int,
        y: int,
        direction: str,
        amount: int = 3,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        """Scroll at position in the given direction with optional modifier keys held."""
        ...

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        """Click-drag from start to end coordinates with optional modifier keys held."""
        ...

    async def wait(self, seconds: float) -> ActionResult:
        """Wait for the specified duration."""
        ...

    def screen_info(self) -> ScreenInfo:
        """Return current screen dimensions and DPI scale."""
        ...

    def screen_context(self) -> ScreenContext:
        """Return current screen context (active window, mouse position)."""
        ...

    async def window_text(self) -> WindowTextResult:
        """Extract all text content from the frontmost window via Accessibility API.

        Returns structured text including content beyond the visible viewport.
        Falls back gracefully when accessibility permissions are unavailable.
        """
        ...

    async def has_blocking_dialog(self, target_app_names: list[str] | None = None) -> bool:
        """Check if there is an OS-level dialog window blocking the target application.

        Args:
            target_app_names: Optional list of app names to check against (e.g., ["Google Chrome", "Chromium"]).
                              If None, checks the frontmost app.

        Returns:
            True if a blocking dialog (like a file picker or permission prompt) is detected.
        """
        ...

    async def is_browser_active(self) -> bool:
        """Check if the currently active (frontmost) window is a web browser.

        Returns:
            True if the frontmost window belongs to a known browser.
        """
        ...

    async def check_permissions(self) -> PermissionStatus:
        """Probe OS-level permissions required for desktop automation.

        Returns:
            PermissionStatus with per-capability booleans and deep-link URLs
            to the OS settings page where the user can grant access.
        """
        ...
