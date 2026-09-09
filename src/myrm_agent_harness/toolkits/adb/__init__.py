"""Android Wireless ADB toolkit public exports (Redirects to SSOT mobile_adb).

[INPUT]
- myrm_agent_harness.toolkits.mobile_adb

[OUTPUT]
- Backward-compatible facades re-exporting from mobile_adb
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.mobile_adb import (
    MobileActionResult,
    MobileDeviceConnectionStatus,
    MobileSafetyGuard,
    MobileSession,
    MobileUIElement,
    create_mobile_adb_tools,
)

# Aliases for compatibility
AdbSafetyGuard = MobileSafetyGuard
AdbBridgeEngine = MobileSession

__all__ = [
    "AdbBridgeEngine",
    "AdbSafetyGuard",
    "MobileActionResult",
    "MobileDeviceConnectionStatus",
    "MobileSafetyGuard",
    "MobileSession",
    "MobileUIElement",
    "create_mobile_adb_tools",
]
