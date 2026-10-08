"""Type definitions for Sandbox Container Device Whitelist Hardening
and Block Device Strip Suite.

[INPUT]
- stdlib dataclasses, enum, typing

[OUTPUT]
- DeviceType: character or block device classification
- DeviceSanitizeAction: ALLOW, STRIP, or REJECT action
- VirtualDeviceSpec: specification of a permissible virtual device node
- DeviceInspectionResult: outcome of inspecting a device node candidate
- DeviceAuditReport: summary report of sanitized container devices
- ContainerDevicePolicyConfig: configuration for container device isolation

[POS]
Core schema definitions for CodePilot-aligned virtual device allowlist and block device stripping.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DeviceType(StrEnum):
    """Device node classification."""

    CHAR = "c"
    BLOCK = "b"


class DeviceSanitizeAction(StrEnum):
    """Enforcement action applied to a device path."""

    ALLOW = "ALLOW"
    STRIP = "STRIP"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class VirtualDeviceSpec:
    """Specification of an authorized in-sandbox virtual pseudo-device."""

    path: str
    major: int
    minor: int
    device_type: DeviceType = DeviceType.CHAR
    permissions: str = "rwm"
    description: str = ""


@dataclass(frozen=True, slots=True)
class DeviceInspectionResult:
    """Outcome of evaluating a single device node candidate."""

    path: str
    action: DeviceSanitizeAction
    device_type: DeviceType | None
    matched_rule: str
    reason: str


@dataclass(frozen=True, slots=True)
class DeviceAuditReport:
    """Report detailing sanitized device candidates and stripped dangerous nodes."""

    total_inspected: int
    allowed_devices: tuple[str, ...]
    stripped_devices: tuple[str, ...]
    reasons: tuple[str, ...]
    is_fully_compliant: bool


@dataclass(frozen=True, slots=True)
class ContainerDevicePolicyConfig:
    """Configuration governing container device allowlists and stripping."""

    strict_minimal_allowlist: bool = True
    strip_block_devices: bool = True
    strip_host_hardware_devices: bool = True
    custom_allowed_devices: tuple[str, ...] = field(default_factory=tuple)
