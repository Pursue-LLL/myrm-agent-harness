"""Mobile device ADB automation and wireless bridge toolkit.

[INPUT]
- types, protocols, device_manager, inspector, input_controller, app_manager, mobile_agent_tools

[OUTPUT]
- create_mobile_tools, AdbDeviceManager, MobileInspector, MobileInputController, MobileAppManager

[POS]
Toolkit root exporting core abstractions, implementations, and LangChain Agent tools.
"""

from __future__ import annotations

from .app_manager import MobileAppManager
from .device_manager import AdbDeviceManager
from .input_controller import MobileInputController
from .inspector import MobileInspector
from .mobile_agent_tools import create_mobile_tools
from .protocols import (
    MobileAppManagerProtocol,
    MobileDeviceBackendProtocol,
    MobileInputProtocol,
    MobileInspectorProtocol,
)
from .types import (
    DeviceConnectionState,
    MobileActionResult,
    MobileDeviceInfo,
    MobileElementNode,
    MobileKeyEvent,
    MobileTouchAction,
)

__all__ = [
    "AdbDeviceManager",
    "DeviceConnectionState",
    "MobileActionResult",
    "MobileAppManager",
    "MobileAppManagerProtocol",
    "MobileDeviceBackendProtocol",
    "MobileDeviceInfo",
    "MobileElementNode",
    "MobileInputController",
    "MobileInputProtocol",
    "MobileInspector",
    "MobileInspectorProtocol",
    "MobileKeyEvent",
    "MobileTouchAction",
    "create_mobile_tools",
]
