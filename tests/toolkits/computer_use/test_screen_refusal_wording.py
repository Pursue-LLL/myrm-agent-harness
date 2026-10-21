"""Every desktop entry point refuses an unusable screen with identical wording.

The refusal text is model-facing: a ``ScreenGuard`` string refusal, the ``check_screen_lock_safety``
probe and the interruption errors raised by ``ensure_screen_safe`` must all carry the same bytes,
otherwise the model sees a different explanation depending on which gate fired first.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.computer_use.safety import (
    DISPLAY_SLEEPING_REFUSAL,
    SCREEN_LOCKED_REFUSAL,
    PhysicalSleepInterruptionError,
    ScreenLockedInterruptionError,
    check_screen_lock_safety,
    ensure_screen_safe,
)
from myrm_agent_harness.toolkits.computer_use.screen_detector import ScreenDetector
from myrm_agent_harness.toolkits.computer_use.types import ScreenLockState


def _detector(state: ScreenLockState) -> ScreenDetector:
    detector = ScreenDetector()
    detector.set_override_state(state)
    return detector


@pytest.mark.parametrize(
    ("state", "error_type", "refusal"),
    [
        (ScreenLockState.LOCKED, ScreenLockedInterruptionError, SCREEN_LOCKED_REFUSAL),
        (ScreenLockState.SLEEPING, PhysicalSleepInterruptionError, DISPLAY_SLEEPING_REFUSAL),
    ],
)
def test_interruption_error_carries_the_shared_refusal_wording(
    state: ScreenLockState, error_type: type[RuntimeError], refusal: str
) -> None:
    detector = _detector(state)

    assert check_screen_lock_safety(detector) == refusal
    with pytest.raises(error_type) as raised:
        ensure_screen_safe(detector)

    assert str(raised.value) == refusal


def test_interruption_errors_keep_a_custom_message() -> None:
    assert str(ScreenLockedInterruptionError("custom")) == "custom"
    assert str(PhysicalSleepInterruptionError("custom")) == "custom"
