"""Data structures and type definitions for Code-Over-Prompt and Roundtrip Compression Suite.

Provides structured models for coordinate normalization, screenshot fallback self-healing,
application name resolution, and roundtrip budget enforcement gates.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- CoordinateFormat
- ScreenshotFailureReason
- DisplayBounds
- NormalizedPoint
- WindowDescriptor
- ScreenshotResult
- AppLaunchResolverEntry
- RoundtripBudgetVerdict

[POS]
Data structures and type definitions for Code-Over-Prompt and Roundtrip Compression Suite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class CoordinateFormat(StrEnum):
    """Format of the input coordinates supplied by the agent or caller."""

    PIXEL = "pixel"  # Absolute physical device pixels, e.g. (1920, 1080)
    RETINA_SCALED = "retina_scaled"  # Retina logical points requiring scale factor multiplication, e.g. (960, 540)
    PERCENTAGE = "percentage"  # Normalized floating ratio between 0.0 and 1.0, e.g. (0.5, 0.5)
    AUTO_INFERRED = "auto_inferred"  # Automatically deduced based on coordinate value ranges


class ScreenshotFailureReason(StrEnum):
    """Failure root cause detected when attempting to capture a window surface."""

    BLACK_SCREEN = "black_screen"  # Render buffer returned solid black / zero pixels
    OFFSCREEN_NO_FOCUS = "offscreen_no_focus"  # Window is minimized, off-screen or in another Space
    OCCLUDED = "occluded"  # Window is covered by higher z-order modal or system dialog
    GPU_EMPTY_SURFACE = "gpu_empty_surface"  # Metal / DirectX surface not yet committed
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DisplayBounds:
    """Dimensions and density metrics of the target display."""

    width: int
    height: int
    scale_factor: float = 2.0


@dataclass(frozen=True)
class NormalizedPoint:
    """Resolved physical pixel coordinates ready for OS-level input events."""

    x: int
    y: int
    raw_x: float
    raw_y: float
    format_detected: CoordinateFormat


@dataclass(frozen=True)
class WindowDescriptor:
    """Descriptor for a native operating system application window."""

    window_id: int
    owner_pid: int
    title: str
    width: int
    height: int
    is_on_screen: bool = True
    layer: int = 0


@dataclass(frozen=True)
class ScreenshotResult:
    """Result of an autonomous screenshot operation with self-healing fallback."""

    success: bool
    data_or_token: str
    failure_reason: ScreenshotFailureReason | None = None
    attempted_sibling: bool = False
    sibling_window_id: int | None = None
    roundtrip_cost: int = 1


@dataclass(frozen=True)
class AppLaunchResolverEntry:
    """Registered application identity mapping."""

    display_name: str
    bundle_id: str
    executable_name: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RoundtripBudgetVerdict:
    """Evaluation result from the roundtrip budget gatekeeper."""

    passed: bool
    current_roundtrips: int
    max_budget: int
    exceeded_by: int
    efficiency_ratio: float
    timestamp: float = field(default_factory=time.time)
