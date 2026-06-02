"""Browser CAPTCHA detection and coordination subsystem.

Components:
- ``detect_captcha``: Page-level blocking CAPTCHA detection.
- ``CaptchaCoordinator``: Pause/resume coordination with state machine.
- ``ManualSolver``: Default human-in-the-loop solver.
- Protocol types: ``CaptchaSolver``, ``CaptchaInfo``, ``CaptchaSolveResult``, etc.
"""

from .coordinator import CaptchaCoordinator
from .detector import detect_captcha
from .manual_solver import ManualSolver
from .protocols import (
    CaptchaInfo,
    CaptchaSolver,
    CaptchaSolveResult,
    CaptchaStatus,
    CaptchaType,
)

__all__ = [
    "CaptchaCoordinator",
    "CaptchaInfo",
    "CaptchaSolveResult",
    "CaptchaSolver",
    "CaptchaStatus",
    "CaptchaType",
    "ManualSolver",
    "detect_captcha",
]
