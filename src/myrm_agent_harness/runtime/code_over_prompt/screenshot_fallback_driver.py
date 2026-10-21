"""Autonomous screenshot self-healing driver with sibling window fallback.

Eliminates the anti-pattern of having models diagnose screenshot failure modes
across multiple conversational turns. Diagnoses black screens and occlusions,
automatically falling back to sibling windows within the same application process.

[INPUT]
- __future__
- collections
- code_over_prompt_types

[OUTPUT]
- WindowCaptureCallback
- ScreenshotFallbackDriver

[POS]
Autonomous screenshot self-healing driver with sibling window fallback.
"""

from __future__ import annotations

from collections.abc import Callable

from .code_over_prompt_types import (
    ScreenshotFailureReason,
    ScreenshotResult,
    WindowDescriptor,
)

WindowCaptureCallback = Callable[[int], tuple[bool, str, ScreenshotFailureReason | None]]


class ScreenshotFallbackDriver:
    """Manages screenshot attempts with automated kernel-level sibling fallback."""

    def __init__(self, capture_fn: WindowCaptureCallback) -> None:
        self.capture_fn = capture_fn

    def capture_with_fallback(
        self,
        target_window: WindowDescriptor,
        available_windows: list[WindowDescriptor],
    ) -> ScreenshotResult:
        """Attempt primary window capture; automatically fallback to sibling windows upon failure.

        Preserves the 1-roundtrip invariant: the language model only requests the screenshot once,
        and underlying drivers resolve multi-window complexities.
        """
        # First attempt: capture target window directly
        success, data, failure_reason = self.capture_fn(target_window.window_id)
        if success:
            return ScreenshotResult(
                success=True,
                data_or_token=data,
                attempted_sibling=False,
                roundtrip_cost=1,
            )

        # Fallback phase: find valid siblings belonging to the same application process
        siblings = self._find_candidate_siblings(target_window, available_windows)
        for sibling in siblings:
            sib_success, sib_data, _ = self.capture_fn(sibling.window_id)
            if sib_success:
                return ScreenshotResult(
                    success=True,
                    data_or_token=sib_data,
                    attempted_sibling=True,
                    sibling_window_id=sibling.window_id,
                    roundtrip_cost=1,  # Lowered to code: still counted as a single model roundtrip
                )

        # Terminal failure when all siblings exhausted
        return ScreenshotResult(
            success=False,
            data_or_token="",
            failure_reason=failure_reason or ScreenshotFailureReason.UNKNOWN,
            attempted_sibling=bool(siblings),
            roundtrip_cost=1,
        )

    @staticmethod
    def _find_candidate_siblings(
        target_window: WindowDescriptor,
        available_windows: list[WindowDescriptor],
    ) -> list[WindowDescriptor]:
        """Filter and rank candidate sibling windows owned by the same PID."""
        candidates: list[WindowDescriptor] = []
        for win in available_windows:
            if win.window_id == target_window.window_id:
                continue
            if win.owner_pid != target_window.owner_pid:
                continue
            # Ignore zero-sized or proxy windows (< 100px)
            if win.width < 100 or win.height < 100:
                continue
            if not win.is_on_screen:
                continue
            candidates.append(win)

        # Sort by window area descending (largest visible window first)
        candidates.sort(key=lambda w: w.width * w.height, reverse=True)
        return candidates
