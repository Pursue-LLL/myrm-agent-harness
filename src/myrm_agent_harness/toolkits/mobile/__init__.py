"""Mobile toolkit - Wireless Android Debug Bridge and automation suite.

[INPUT]
- types (POS: domain models, Point2D, MobileNode, ScreencapResult, SensitiveActionVerdict)
- protocols (POS: MobileDeviceManagerProtocol, MobileInspectorProtocol, etc.)
- device_manager (POS: MobileDeviceManager)
- inspector (POS: MobileInspector)
- input_controller (POS: MobileInputController)
- app_manager (POS: MobileAppManager)
- safety (POS: MobileSafetyBarrier)
- mobile_bridge (POS: MobileBridge facade)
- mobile_agent_tools (POS: optional LangChain adapter create_mobile_tools)

[OUTPUT]
- MobileBridge
- MobileDeviceManager
- MobileInspector
- MobileInputController
- MobileAppManager
- MobileSafetyBarrier
- create_mobile_tools

[POS]
Package export entry point for myrm_agent_harness.toolkits.mobile.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.mobile.app_manager import MobileAppManager
from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.input_controller import MobileInputController
from myrm_agent_harness.toolkits.mobile.inspector import MobileInspector
from myrm_agent_harness.toolkits.mobile.mobile_agent_tools import create_mobile_tools
from myrm_agent_harness.toolkits.mobile.mobile_bridge import MobileBridge
from myrm_agent_harness.toolkits.mobile.protocols import (
    MobileAppManagerProtocol,
    MobileBridgeEngineProtocol,
    MobileDeviceManagerProtocol,
    MobileInputControllerProtocol,
    MobileInspectorProtocol,
    MobileSafetyBarrierProtocol,
)
from myrm_agent_harness.toolkits.mobile.safety import MobileSafetyBarrier
from myrm_agent_harness.toolkits.mobile.types import (
    DeviceConnectionMode,
    DeviceState,
    ElementBounds,
    KeyCode,
    MobileActionResult,
    MobileDevice,
    MobileHierarchy,
    MobileNode,
    Point2D,
    ScreencapResult,
    SensitiveActionVerdict,
    TouchAction,
)

__all__ = [
    "DeviceConnectionMode",
    "DeviceState",
    "ElementBounds",
    "KeyCode",
    "MobileActionResult",
    "MobileAppManager",
    "MobileAppManagerProtocol",
    "MobileBridge",
    "MobileBridgeEngineProtocol",
    "MobileDevice",
    "MobileDeviceManager",
    "MobileDeviceManagerProtocol",
    "MobileHierarchy",
    "MobileInputController",
    "MobileInputControllerProtocol",
    "MobileInspector",
    "MobileInspectorProtocol",
    "MobileNode",
    "MobileSafetyBarrier",
    "MobileSafetyBarrierProtocol",
    "Point2D",
    "ScreencapResult",
    "SensitiveActionVerdict",
    "TouchAction",
    "create_mobile_tools",
]
