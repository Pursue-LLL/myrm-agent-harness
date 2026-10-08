"""Device sanitizer and allowlist engine for sandbox containers.

[INPUT]
- .types::(ContainerDevicePolicyConfig, DeviceAuditReport, DeviceInspectionResult,
           DeviceSanitizeAction, DeviceType, VirtualDeviceSpec)
- stdlib fnmatch, logging, re

[OUTPUT]
- ContainerDeviceSanitizer: sanitizes device paths, strips block devices,
  and generates cgroup isolation rules aligned with CodePilot

[POS]
Device-level sandbox security boundary. Enforces minimal virtual pseudo-device allowlist
and strips physical block devices and host hardware nodes.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Sequence

from myrm_agent_harness.core.security.device_whitelist.types import (
    ContainerDevicePolicyConfig,
    DeviceAuditReport,
    DeviceInspectionResult,
    DeviceSanitizeAction,
    DeviceType,
    VirtualDeviceSpec,
)

logger = logging.getLogger(__name__)

# The strictly authorized virtual pseudo-devices (CodePilot L295-306 alignment)
STANDARD_VIRTUAL_DEVICES: tuple[VirtualDeviceSpec, ...] = (
    VirtualDeviceSpec(path="/dev/null", major=1, minor=3, device_type=DeviceType.CHAR, description="Null device"),
    VirtualDeviceSpec(path="/dev/zero", major=1, minor=5, device_type=DeviceType.CHAR, description="Zero byte source"),
    VirtualDeviceSpec(path="/dev/full", major=1, minor=7, device_type=DeviceType.CHAR, description="Always-full device"),
    VirtualDeviceSpec(path="/dev/random", major=1, minor=8, device_type=DeviceType.CHAR, description="Kernel entropy"),
    VirtualDeviceSpec(path="/dev/urandom", major=1, minor=9, device_type=DeviceType.CHAR, description="Non-blocking entropy"),
    VirtualDeviceSpec(path="/dev/tty", major=5, minor=0, device_type=DeviceType.CHAR, description="Controlling terminal"),
    VirtualDeviceSpec(path="/dev/ptmx", major=5, minor=2, device_type=DeviceType.CHAR, description="Pseudoterminal multiplexer"),
)

# Block device glob patterns (physical disk partitions, nvme, virtual block devices)
_BLOCK_DEVICE_PATTERNS: tuple[str, ...] = (
    "/dev/sd*",        # SCSI/SATA disks (e.g. /dev/sda, /dev/sdb1)
    "/dev/nvme*",      # NVMe SSDs
    "/dev/vd*",        # VirtIO virtual block devices
    "/dev/hd*",        # IDE disks
    "/dev/loop*",      # Loopback devices
    "/dev/mmcblk*",    # MMC/SD cards
    "/dev/dm-*",       # Device mapper (LVM / cryptsetup)
    "/dev/md*",        # Software RAID
    "/dev/bcache*",    # Block cache
    "/dev/zram*",      # Compressed RAM block devices
)

# Dangerous host system and hardware devices
_HOST_SYSTEM_DEVICE_PATTERNS: tuple[str, ...] = (
    "/dev/mem",
    "/dev/kmem",
    "/dev/port",
    "/dev/kmsg",
    "/dev/dri*",       # Direct Rendering Infrastructure
    "/dev/kvm",        # Kernel-based Virtual Machine
    "/dev/snd*",       # Sound cards
    "/dev/input*",     # Input devices (keyboards/mice)
    "/dev/bus/usb*",   # USB bus
    "/dev/vhost*",     # Vhost kernel drivers
)


class ContainerDeviceSanitizer:
    """Sanitizer enforcing strict device node boundaries for container sandboxes."""

    def __init__(self, config: ContainerDevicePolicyConfig | None = None) -> None:
        self._config = config or ContainerDevicePolicyConfig()
        self._allowed_paths: frozenset[str] = frozenset(
            d.path for d in STANDARD_VIRTUAL_DEVICES
        ).union(self._config.custom_allowed_devices)

    @property
    def config(self) -> ContainerDevicePolicyConfig:
        return self._config

    def inspect_device(self, device_path: str) -> DeviceInspectionResult:
        """Inspect a single device candidate and determine whether to allow or strip it."""
        norm_path = device_path.strip().rstrip("/")
        if not norm_path.startswith("/dev/"):
            norm_path = "/dev/" + norm_path.lstrip("/")

        # 1. Allowed virtual pseudo-devices
        if norm_path in self._allowed_paths or fnmatch.fnmatch(norm_path, "/dev/pts/*"):
            return DeviceInspectionResult(
                path=norm_path,
                action=DeviceSanitizeAction.ALLOW,
                device_type=DeviceType.CHAR,
                matched_rule="ALLOWED_VIRTUAL_DEVICE",
                reason=f"Path '{norm_path}' is an authorized virtual pseudo-device",
            )

        # 2. Block device stripping
        if self._config.strip_block_devices:
            for pattern in _BLOCK_DEVICE_PATTERNS:
                if fnmatch.fnmatch(norm_path, pattern):
                    return DeviceInspectionResult(
                        path=norm_path,
                        action=DeviceSanitizeAction.STRIP,
                        device_type=DeviceType.BLOCK,
                        matched_rule="STRIPPED_PHYSICAL_BLOCK_DEVICE",
                        reason=f"Path '{norm_path}' matches physical/virtual block device pattern '{pattern}'",
                    )

        # 3. Host system hardware device stripping
        if self._config.strip_host_hardware_devices:
            for pattern in _HOST_SYSTEM_DEVICE_PATTERNS:
                if fnmatch.fnmatch(norm_path, pattern):
                    return DeviceInspectionResult(
                        path=norm_path,
                        action=DeviceSanitizeAction.STRIP,
                        device_type=DeviceType.CHAR,
                        matched_rule="STRIPPED_HOST_HARDWARE_DEVICE",
                        reason=f"Path '{norm_path}' matches privileged host hardware pattern '{pattern}'",
                    )

        # 4. Strict minimal allowlist: reject any unknown devices
        if self._config.strict_minimal_allowlist:
            return DeviceInspectionResult(
                path=norm_path,
                action=DeviceSanitizeAction.STRIP,
                device_type=None,
                matched_rule="UNKNOWN_DEVICE_NON_ALLOWLISTED",
                reason=f"Path '{norm_path}' is not present in the strict virtual device allowlist",
            )

        return DeviceInspectionResult(
            path=norm_path,
            action=DeviceSanitizeAction.ALLOW,
            device_type=None,
            matched_rule="UNRESTRICTED_FALLBACK",
            reason="Device passed through unrestricted policy",
        )

    def sanitize_device_list(self, devices: Sequence[str]) -> DeviceAuditReport:
        """Sanitize a collection of device paths for container startup."""
        allowed: list[str] = []
        stripped: list[str] = []
        reasons: list[str] = []

        for dev in devices:
            res = self.inspect_device(dev)
            if res.action == DeviceSanitizeAction.ALLOW:
                allowed.append(res.path)
            else:
                stripped.append(res.path)
                reasons.append(f"[{res.matched_rule}] {res.reason}")
                logger.warning("DEVICE STRIPPED from container: %s (Reason: %s)", res.path, res.reason)

        is_clean = len(stripped) == 0
        return DeviceAuditReport(
            total_inspected=len(devices),
            allowed_devices=tuple(allowed),
            stripped_devices=tuple(stripped),
            reasons=tuple(reasons),
            is_fully_compliant=is_clean,
        )

    def generate_cgroup_device_rules(self) -> tuple[str, ...]:
        """Generate cgroup device whitelist rules for Docker/OCI runtime.

        Syntax: [type] [major]:[minor] [permissions]
        - 'c 1:3 rwm' (/dev/null)
        - 'b *:* rmw' (strictly omitted - block devices denied by default)
        """
        rules: list[str] = []
        for dev in STANDARD_VIRTUAL_DEVICES:
            rules.append(f"{dev.device_type.value} {dev.major}:{dev.minor} {dev.permissions}")
        # Allow pseudoterminal slaves
        rules.append("c 136:* rwm")
        return tuple(rules)

    def generate_docker_device_args(self) -> tuple[str, ...]:
        """Generate hardened Docker CLI arguments explicitly mapping only allowed devices."""
        args: list[str] = []
        for rule in self.generate_cgroup_device_rules():
            args.append(f"--device-cgroup-rule={rule}")
        return tuple(args)
