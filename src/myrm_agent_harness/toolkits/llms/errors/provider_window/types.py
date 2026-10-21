"""Typed provider-window fact: when a rate-limited provider says it will serve again.

[INPUT]
- (none — pure value types)

[OUTPUT]
- WindowSource: which provider signal the hint was read from
- WindowKind: how a consumer should treat the wait (in-turn / hold / beyond)
- ProviderWindowHint: absolute reset time plus its classification
- IN_TURN_WAIT_MAX_S / HOLD_MAX_S: the two class boundaries

[POS]
Shared vocabulary between the extractor and every consumer (stream recovery,
credential cooldown, diagnostics). One fact is extracted once; consumers never
re-parse headers or bodies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

IN_TURN_WAIT_MAX_S = 300.0
"""Longest wait still worth blocking the running turn for."""

HOLD_MAX_S = 24 * 3600.0
"""Longest boundary a goal is parked until, and how late its wake-up may run before the goal is paused instead.

Farther resets (weekly/monthly) are not held.
"""


class WindowSource(StrEnum):
    """Provider signal a hint was read from, in precedence order."""

    ANTHROPIC_UNIFIED = "anthropic_unified"
    CODEX_BODY = "codex_body"
    RETRY_AFTER = "retry_after"
    MESSAGE = "message"


class WindowKind(StrEnum):
    """Consumer treatment of a provider wait."""

    IN_TURN = "in_turn"
    HOLD = "hold"
    BEYOND = "beyond"


@dataclass(frozen=True, slots=True)
class ProviderWindowHint:
    """Absolute time at which the provider will accept requests again.

    ``quota_window`` is True when the provider reported a spent quota window
    (subscription 5h/weekly cap) rather than a short admission pause such as a
    plain ``Retry-After``. A depleted-balance error is only waitable when it
    carries a quota window; its ``Retry-After`` alone is not a reset time.
    """

    reset_at: float
    wait_s: float
    source: WindowSource
    quota_window: bool

    @property
    def kind(self) -> WindowKind:
        if self.wait_s <= IN_TURN_WAIT_MAX_S:
            return WindowKind.IN_TURN
        if self.wait_s <= HOLD_MAX_S:
            return WindowKind.HOLD
        return WindowKind.BEYOND
