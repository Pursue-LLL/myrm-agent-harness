"""Code-Over-Prompt and Roundtrip Compression Governance Suite.

Lowering heuristics and arithmetic into deterministic code engines to compress
agent conversational roundtrips by over 75%.

[INPUT]
- app_display_name_resolver
- code_over_prompt_types
- coordinate_normalizer
- roundtrip_budget_gate
- screenshot_fallback_driver

[OUTPUT]
- (模块级副作用与注册)

[POS]
Code-Over-Prompt and Roundtrip Compression Governance Suite.
"""

from .app_display_name_resolver import AppDisplayNameResolver
from .code_over_prompt_types import (
    AppLaunchResolverEntry,
    CoordinateFormat,
    DisplayBounds,
    NormalizedPoint,
    RoundtripBudgetVerdict,
    ScreenshotFailureReason,
    ScreenshotResult,
    WindowDescriptor,
)
from .coordinate_normalizer import CoordinateNormalizer
from .roundtrip_budget_gate import RoundtripBudgetGate
from .screenshot_fallback_driver import ScreenshotFallbackDriver

__all__ = [
    "AppDisplayNameResolver",
    "AppLaunchResolverEntry",
    "CoordinateFormat",
    "CoordinateNormalizer",
    "DisplayBounds",
    "NormalizedPoint",
    "RoundtripBudgetGate",
    "RoundtripBudgetVerdict",
    "ScreenshotFallbackDriver",
    "ScreenshotFailureReason",
    "ScreenshotResult",
    "WindowDescriptor",
]
