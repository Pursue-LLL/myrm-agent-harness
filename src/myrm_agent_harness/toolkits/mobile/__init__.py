"""Android Wireless ADB & Mobile Device Automation Toolkit.

[INPUT]
- mobile_bridge::MobileBridge, create_mobile_bridge (POS: facade)
- types::DeviceInfo, UIElementNode, MobileActionResult, MobileScreenshotResult, MobileUIDumpResult (POS: shared types)
- protocols::MobileBridgeProtocol, MobileDeviceManagerProtocol, MobileInspectorProtocol, MobileInputControllerProtocol, MobileAppManagerProtocol (POS: contracts)

[OUTPUT]
- MobileBridge, create_mobile_bridge, DeviceInfo, UIElementNode, MobileActionResult, MobileScreenshotResult, MobileUIDumpResult

[POS]
Generic Android ADB automation package.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.mobile.app_manager import MobileAppManager
from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.input_controller import MobileInputController
from myrm_agent_harness.toolkits.mobile.inspector import MobileInspector
from myrm_agent_harness.toolkits.mobile.mobile_bridge import (
    MobileBridge,
    create_mobile_bridge,
)
from myrm_agent_harness.toolkits.mobile.protocols import (
    MobileAppManagerProtocol,
    MobileBridgeProtocol,
    MobileDeviceManagerProtocol,
    MobileInputControllerProtocol,
    MobileInspectorProtocol,
)
from myrm_agent_harness.toolkits.mobile.safety import MobileSafetyGuard
from myrm_agent_harness.toolkits.mobile.types import (
    DeviceConnectionStatus,
    DeviceInfo,
    MobileActionResult,
    MobileActionType,
    MobileKey,
    MobileScreenshotResult,
    MobileUIDumpResult,
    TouchGesture,
    UIElementNode,
)

__all__ = [
    "DeviceConnectionStatus",
    "DeviceInfo",
    "MobileActionResult",
    "MobileActionType",
    "MobileAppManager",
    "MobileAppManagerProtocol",
    "MobileBridge",
    "MobileBridgeProtocol",
    "MobileDeviceManager",
    "MobileDeviceManagerProtocol",
    "MobileInputController",
    "MobileInputControllerProtocol",
    "MobileInspector",
    "MobileInspectorProtocol",
    "MobileKey",
    "MobileSafetyGuard",
    "MobileScreenshotResult",
    "MobileUIDumpResult",
    "TouchGesture",
    "UIElementNode",
    "create_mobile_bridge",
]
