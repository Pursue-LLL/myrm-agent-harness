"""Browser CAPTCHA detection and coordination subsystem.

Components:
- ``detect_captcha``: Page-level blocking CAPTCHA detection.
- ``CaptchaCoordinator``: Pause/resume coordination with state machine.
- ``ManualSolver``: Default human-in-the-loop solver.
- ``ApiSolver``: Automatic solver via CapSolver REST API.
- ``FallbackSolver``: Chain-of-responsibility (ApiSolver → ManualSolver).
- Protocol types: ``CaptchaSolver``, ``CaptchaInfo``, ``CaptchaSolveResult``, ``CaptchaHandleResult``, etc.
"""

from .api_solver import ApiSolver
from .coordinator import CaptchaCoordinator
from .detector import detect_captcha
from .fallback_solver import FallbackSolver
from .manual_solver import ManualSolver
from .protocols import (
    CaptchaHandleResult,
    CaptchaInfo,
    CaptchaSolver,
    CaptchaSolveResult,
    CaptchaStatus,
    CaptchaType,
)

__all__ = [
    "ApiSolver",
    "CaptchaCoordinator",
    "CaptchaHandleResult",
    "CaptchaInfo",
    "CaptchaSolveResult",
    "CaptchaSolver",
    "CaptchaStatus",
    "CaptchaType",
    "FallbackSolver",
    "ManualSolver",
    "detect_captcha",
]
