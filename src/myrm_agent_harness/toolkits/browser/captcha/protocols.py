"""CAPTCHA detection and solving protocol definitions.

[INPUT]
- (none)

[OUTPUT]
- CaptchaType: CAPTCHA provider classification enum
- CaptchaStatus: CAPTCHA coordination state machine enum
- CaptchaInfo: detected CAPTCHA metadata (frozen dataclass)
- CaptchaSolveResult: solver outcome (frozen dataclass)
- CaptchaSolver: pluggable solver protocol (async)

[POS]
Pure data types and protocol definitions for the browser CAPTCHA subsystem.
Zero dependencies on runtime components — importable by any layer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from patchright.async_api import Page


class CaptchaType(StrEnum):
    """Known CAPTCHA provider types."""

    CLOUDFLARE_CHALLENGE = "cloudflare_challenge"
    CLOUDFLARE_TURNSTILE = "cloudflare_turnstile"
    RECAPTCHA = "recaptcha"
    HCAPTCHA = "hcaptcha"
    PERIMETERX = "perimeterx"
    DATADOME = "datadome"
    KASADA = "kasada"
    AKAMAI = "akamai"
    IMPERVA = "imperva"
    UNKNOWN = "unknown"


class CaptchaStatus(StrEnum):
    """CAPTCHA coordination state machine.

    State transitions:
        NONE → DETECTED → SOLVING → RESOLVED | TIMEOUT
    """

    NONE = "none"
    DETECTED = "detected"
    SOLVING = "solving"
    RESOLVED = "resolved"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class CaptchaInfo:
    """Detected CAPTCHA metadata.

    Attributes:
        captcha_type: Provider classification.
        reason: Human-readable detection reason (e.g. "Cloudflare JS challenge").
        blocking: True if the CAPTCHA blocks the entire page (vs. embedded widget).
        confidence: Detection confidence (0.0–1.0). Tier-1 patterns yield ~1.0.
        detected_at: Monotonic timestamp of detection.
    """

    captcha_type: CaptchaType
    reason: str
    blocking: bool = True
    confidence: float = 1.0
    detected_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class CaptchaSolveResult:
    """Outcome of a solve attempt.

    Attributes:
        success: Whether the CAPTCHA was solved.
        method: Solver method used (e.g. "manual", "2captcha").
        elapsed_ms: Wall-clock time spent solving.
        message: Optional diagnostic message.
    """

    success: bool
    method: str
    elapsed_ms: float
    message: str = ""


@runtime_checkable
class CaptchaSolver(Protocol):
    """Pluggable CAPTCHA solver interface.

    Implementations must be async. The framework ships ``ManualSolver``
    as the default; third-party auto-solvers (2captcha, CapSolver, etc.)
    can implement this protocol without any harness dependency.
    """

    async def solve(
        self,
        captcha_info: CaptchaInfo,
        page: Page,
    ) -> CaptchaSolveResult:
        """Attempt to solve the detected CAPTCHA.

        Args:
            captcha_info: Metadata about the detected CAPTCHA.
            page: The Patchright page containing the CAPTCHA.

        Returns:
            Result indicating success/failure and diagnostics.
        """
        ...
