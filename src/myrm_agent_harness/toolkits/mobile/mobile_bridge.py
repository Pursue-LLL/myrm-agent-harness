"""Unified Mobile Bridge Facade.

[INPUT]
- device_manager::MobileDeviceManager
- inspector::MobileInspector
- input_controller::MobileInputController
- app_manager::MobileAppManager
- safety::MobileSafetyGuard

[OUTPUT]
- MobileBridge: Unified facade class coordinating all Android ADB operations

[POS]
Main entrypoint for mobile device automation.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.mobile.app_manager import MobileAppManager
from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.input_controller import MobileInputController
from myrm_agent_harness.toolkits.mobile.inspector import MobileInspector
from myrm_agent_harness.toolkits.mobile.protocols import MobileBridgeProtocol
from myrm_agent_harness.toolkits.mobile.safety import MobileSafetyGuard


class MobileBridge:
    """Unified facade for mobile Android automation."""

    def __init__(
        self,
        adb_path: str = "adb",
        allow_high_risk: bool = False,
    ) -> None:
        self.safety_guard = MobileSafetyGuard(allow_high_risk=allow_high_risk)
        self.device_manager = MobileDeviceManager(adb_path=adb_path)
        self.inspector = MobileInspector(self.device_manager, self.safety_guard)
        self.input_controller = MobileInputController(self.device_manager, self.safety_guard)
        self.app_manager = MobileAppManager(self.device_manager)


def create_mobile_bridge(adb_path: str = "adb", allow_high_risk: bool = False) -> MobileBridge:
    """Factory creating a fully configured MobileBridge instance."""
    return MobileBridge(adb_path=adb_path, allow_high_risk=allow_high_risk)
