"""Android Mobile Device Automation Toolkit (Facade re-exporting to SSOT mobile_adb).

[INPUT]
- myrm_agent_harness.toolkits.mobile_adb

[OUTPUT]
- Backward-compatible facades re-exporting from mobile_adb
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.mobile_adb import (
    AdbDeviceDriver,
    MobileActionResult,
    MobileActionType,
    MobileDeviceConnectionStatus,
    MobileDeviceState,
    MobileSafetyGuard,
    MobileSession,
    MobileUIElement,
    create_mobile_adb_tools,
)

# Aliases for compatibility
MobileDeviceManager = MobileSession
AdbDeviceManager = MobileSession
UIElementNode = MobileUIElement
DeviceConnectionStatus = MobileDeviceConnectionStatus

__all__ = [
    "AdbDeviceDriver",
    "AdbDeviceManager",
    "DeviceConnectionStatus",
    "MobileActionResult",
    "MobileActionType",
    "MobileDeviceConnectionStatus",
    "MobileDeviceManager",
    "MobileDeviceState",
    "MobileSafetyGuard",
    "MobileSession",
    "MobileUIElement",
    "UIElementNode",
    "create_mobile_adb_tools",
]
