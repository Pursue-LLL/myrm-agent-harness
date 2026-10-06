"""Computer Use toolkit — semantic desktop control (SDC).

Public API:
- create_desktop_tools: factory for LangChain tools
- create_desktop_session: session factory
- DesktopSession: semantic desktop session with @dref registry
"""

from myrm_agent_harness.toolkits.computer_use.desktop_agent_tools import create_desktop_tools
from myrm_agent_harness.toolkits.computer_use.desktop_session import (
    DesktopSession,
    create_desktop_session,
)
from myrm_agent_harness.toolkits.computer_use.envelope import (
    EnvelopeCheckResult,
    IntentEnvelopeSpec,
    KeystrokeSanitizer,
    WindowHierarchyContext,
    check_envelope_action,
)
from myrm_agent_harness.toolkits.computer_use.mcp_server import (
    DesktopMCPServer,
    get_request_desktop_session,
    register_desktop_mcp_tools,
    reset_request_desktop_session,
    set_request_desktop_session,
)
from myrm_agent_harness.toolkits.computer_use.safety import (
    PhysicalSleepInterruptionError,
    ScreenLockedInterruptionError,
    check_screen_lock_safety,
    ensure_screen_safe,
)
from myrm_agent_harness.toolkits.computer_use.screen_detector import (
    ScreenDetector,
    get_default_screen_detector,
    hid_idle_seconds,
)
from myrm_agent_harness.toolkits.computer_use.session import (
    ComputerSession,
    create_computer_session,
)
from myrm_agent_harness.toolkits.computer_use.types import ScreenLockState

__all__ = [
    "ComputerSession",
    "DesktopMCPServer",
    "DesktopSession",
    "EnvelopeCheckResult",
    "IntentEnvelopeSpec",
    "KeystrokeSanitizer",
    "PhysicalSleepInterruptionError",
    "ScreenDetector",
    "ScreenLockState",
    "ScreenLockedInterruptionError",
    "WindowHierarchyContext",
    "check_envelope_action",
    "check_screen_lock_safety",
    "create_computer_session",
    "create_desktop_session",
    "create_desktop_tools",
    "ensure_screen_safe",
    "get_default_screen_detector",
    "get_request_desktop_session",
    "hid_idle_seconds",
    "register_desktop_mcp_tools",
    "reset_request_desktop_session",
    "set_request_desktop_session",
]
