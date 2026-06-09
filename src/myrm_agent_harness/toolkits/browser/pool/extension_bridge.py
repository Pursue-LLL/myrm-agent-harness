"""Extension Bridge Protocol for browser extension CDP proxy integration.

[INPUT]
- typing::Protocol, runtime_checkable (POS: Python Protocol for structural subtyping)

[OUTPUT]
- ExtensionBridge: Protocol defining the contract for browser extension bridge implementations
- ExtensionTab: data class representing a browser tab exposed by the extension

[POS]
Defines the framework-level Protocol that business layers (myrm-agent-server) must implement
to provide browser extension bridge functionality. The harness layer only depends on this
Protocol — it never imports concrete implementations, maintaining strict layer separation.

The extension bridge allows the Agent to control the user's everyday browser through a
Chrome/Edge MV3 extension that acts as a CDP proxy over WebSocket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .browser_launcher import BrowserInstance


@dataclass(frozen=True)
class ExtensionTab:
    """Metadata for a browser tab exposed by the extension.

    Attributes:
        tab_id: Chrome-internal tab ID.
        url: Current URL of the tab.
        title: Current page title.
        domain: Extracted domain from URL for authorization checks.
        active: Whether this is the currently active tab.
    """

    tab_id: int
    url: str
    title: str
    domain: str
    active: bool = False


@dataclass
class ExtensionStatus:
    """Real-time status of the extension connection.

    Attributes:
        connected: Whether the extension WebSocket is currently connected.
        extension_version: Version string reported by the extension.
        browser_name: Browser name (e.g., "Chrome", "Edge").
        authorized_domains: Domains the user has granted access to.
        available_tabs: Tabs currently open that match authorized domains.
        last_heartbeat_at: Monotonic timestamp of last successful heartbeat.
    """

    connected: bool = False
    extension_version: str = ""
    browser_name: str = ""
    authorized_domains: list[str] = field(default_factory=list)
    available_tabs: list[ExtensionTab] = field(default_factory=list)
    last_heartbeat_at: float = 0.0


@runtime_checkable
class ExtensionBridge(Protocol):
    """Protocol for browser extension bridge implementations.

    Business layer (myrm-agent-server) implements this Protocol to provide
    the actual WebSocket connection management and CDP message routing.
    The harness layer's BrowserLauncher uses this to obtain a BrowserInstance
    when LaunchMode.EXTENSION is configured.
    """

    async def connect(self, *, timeout: float = 10.0) -> BrowserInstance:
        """Obtain a BrowserInstance by connecting through the extension.

        The implementation should:
        1. Verify the extension WebSocket is connected
        2. Select an appropriate tab (based on authorized domains)
        3. Attach chrome.debugger to the selected tab
        4. Expose the CDP session as a Playwright-compatible endpoint

        Args:
            timeout: Maximum seconds to wait for connection.

        Returns:
            BrowserInstance with is_managed=False (we don't own the browser lifecycle).

        Raises:
            BrowserLaunchError: If extension is not connected or connection fails.
        """
        ...

    async def connect_to_domain(self, domain: str, *, timeout: float = 10.0) -> BrowserInstance:
        """Connect to a specific authorized domain's tab.

        Args:
            domain: Target domain (e.g., "github.com").
            timeout: Maximum seconds to wait.

        Returns:
            BrowserInstance connected to a tab matching the domain.

        Raises:
            BrowserLaunchError: If no tab for the domain exists or domain is not authorized.
        """
        ...

    async def get_status(self) -> ExtensionStatus:
        """Get current extension connection status.

        Returns:
            ExtensionStatus with connection state, authorized domains, and available tabs.
        """
        ...

    def is_connected(self) -> bool:
        """Check if the extension WebSocket is currently connected.

        This is a synchronous, non-blocking check suitable for fast path decisions.
        """
        ...

    async def list_tabs(self) -> list[ExtensionTab]:
        """List all tabs available through the extension.

        Only returns tabs whose domains are in the authorized list.
        """
        ...

    async def disconnect(self) -> None:
        """Gracefully disconnect from the extension.

        Detaches any active chrome.debugger sessions and closes the WebSocket.
        """
        ...


class ExtensionBridgeNotAvailable(Exception):
    """Raised when extension bridge is required but not connected."""

    def __init__(self, message: str = "Browser extension is not connected") -> None:
        super().__init__(message)
