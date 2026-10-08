"""Facade for Sandbox Container Device Whitelist Hardening
and Block Device Strip Suite.

[INPUT]
- .types::(ContainerDevicePolicyConfig, DeviceAuditReport, DeviceInspectionResult,
           DeviceSanitizeAction, DeviceType, VirtualDeviceSpec)
- .sanitizer::(ContainerDeviceSanitizer, STANDARD_VIRTUAL_DEVICES)
- stdlib collections.abc, threading

[OUTPUT]
- ContainerDeviceWhitelistFacade: unified orchestration of virtual device allowlists,
  block device stripping, and container cgroup rules generation

[POS]
Main entry point for container device hardening in harness.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

from myrm_agent_harness.core.security.device_whitelist.sanitizer import (
    STANDARD_VIRTUAL_DEVICES,
    ContainerDeviceSanitizer,
)
from myrm_agent_harness.core.security.device_whitelist.types import (
    ContainerDevicePolicyConfig,
    DeviceAuditReport,
    DeviceInspectionResult,
    VirtualDeviceSpec,
)


class ContainerDeviceWhitelistFacade:
    """Unified facade managing sandbox device allowlists, block device stripping, and cgroup rules."""

    def __init__(self, config: ContainerDevicePolicyConfig | None = None) -> None:
        self._config = config or ContainerDevicePolicyConfig()
        self._sanitizer = ContainerDeviceSanitizer(self._config)
        self._lock = threading.Lock()

    @property
    def config(self) -> ContainerDevicePolicyConfig:
        return self._config

    @property
    def sanitizer(self) -> ContainerDeviceSanitizer:
        return self._sanitizer

    def update_config(self, config: ContainerDevicePolicyConfig) -> None:
        """Update policy configuration and reinitialize sanitizer."""
        with self._lock:
            self._config = config
            self._sanitizer = ContainerDeviceSanitizer(config)

    def inspect_device(self, device_path: str) -> DeviceInspectionResult:
        """Inspect a single device path and return safety determination."""
        return self._sanitizer.inspect_device(device_path)

    def sanitize_device_list(self, devices: Sequence[str]) -> DeviceAuditReport:
        """Sanitize a collection of device paths for container startup."""
        return self._sanitizer.sanitize_device_list(devices)

    def get_cgroup_device_rules(self) -> list[str]:
        """Return list of cgroup device permission rules for OCI/Docker."""
        return list(self._sanitizer.generate_cgroup_device_rules())

    def get_docker_device_args(self) -> list[str]:
        """Return list of hardened docker CLI arguments for device restrictions."""
        return list(self._sanitizer.generate_docker_device_args())

    def get_standard_virtual_devices(self) -> list[VirtualDeviceSpec]:
        """Return list of standard authorized virtual pseudo-devices."""
        return list(STANDARD_VIRTUAL_DEVICES)
