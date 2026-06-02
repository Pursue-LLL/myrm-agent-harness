"""Tests for captcha module imports and public API."""

from __future__ import annotations


def test_captcha_package_imports() -> None:
    """All public symbols importable from captcha package."""
    from myrm_agent_harness.toolkits.browser.captcha import (
        CaptchaCoordinator,
        CaptchaInfo,
        CaptchaSolver,
        CaptchaSolveResult,
        CaptchaStatus,
        CaptchaType,
        ManualSolver,
        detect_captcha,
    )

    assert CaptchaCoordinator is not None
    assert CaptchaInfo is not None
    assert CaptchaSolveResult is not None
    assert CaptchaSolver is not None
    assert CaptchaStatus is not None
    assert CaptchaType is not None
    assert ManualSolver is not None
    assert detect_captcha is not None


def test_all_exports_match() -> None:
    """__all__ contains all expected symbols."""
    from myrm_agent_harness.toolkits.browser.captcha import __all__

    expected = {
        "CaptchaCoordinator",
        "CaptchaInfo",
        "CaptchaSolveResult",
        "CaptchaSolver",
        "CaptchaStatus",
        "CaptchaType",
        "ManualSolver",
        "detect_captcha",
    }
    assert set(__all__) == expected
