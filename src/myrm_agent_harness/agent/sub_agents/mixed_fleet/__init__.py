"""Mixed Fleet Local Brain and Remote Executor Preset Pack (Item 47).

Provides coordination between a privacy/memory-preserving Local Brain and
an always-on 24/7 Remote Executor sandbox via structured markdown handoffs.

[INPUT]
- fleet_coordinator
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Mixed Fleet Local Brain and Remote Executor Preset Pack (Item 47).
"""

from .fleet_coordinator import MixedFleetCoordinator
from .types import (
    DispatchHandoffRequest,
    FleetExecutionStatusEnum,
    FleetNodeSpec,
    FleetRoleEnum,
    FleetStatusSnapshot,
    MixedFleetError,
    MixedFleetHandoffManifest,
    MixedFleetHandoffNotFoundError,
    MixedFleetOfflineError,
)

__all__ = [
    "DispatchHandoffRequest",
    "FleetExecutionStatusEnum",
    "FleetNodeSpec",
    "FleetRoleEnum",
    "FleetStatusSnapshot",
    "MixedFleetCoordinator",
    "MixedFleetError",
    "MixedFleetHandoffManifest",
    "MixedFleetHandoffNotFoundError",
    "MixedFleetOfflineError",
]
