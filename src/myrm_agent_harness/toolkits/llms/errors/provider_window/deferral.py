"""How long a goal-less caller may defer its work after a provider window error.

[INPUT]
- errors.exceptions::MyrmLLMError (POS: fatal stream error; ``context['cooldown_remaining_ms']`` carries the provider boundary)
- provider_window.types::HOLD_MAX_S (POS: longest boundary worth holding for)

[OUTPUT]
- deferral_wait_s: seconds until the provider accepts requests again, only when that is waitable

[POS]
Host schedulers without a goal to park (cron jobs, kanban tasks) call this on a failed run
and re-arm themselves at the stated boundary instead of burning retries on a closed window.
Boundaries beyond the hold cap return None, so those runs keep their normal failure path.
"""

from __future__ import annotations

from ..exceptions import MyrmLLMError
from .types import HOLD_MAX_S

_COOLDOWN_CONTEXT_KEY = "cooldown_remaining_ms"


def deferral_wait_s(exc: BaseException) -> float | None:
    """Seconds to wait before retrying *exc*'s call, or None when no waitable boundary is stated."""
    if not isinstance(exc, MyrmLLMError):
        return None
    cooldown_ms = exc.context.get(_COOLDOWN_CONTEXT_KEY)
    if not isinstance(cooldown_ms, int) or isinstance(cooldown_ms, bool) or cooldown_ms <= 0:
        return None
    wait_s = cooldown_ms / 1000
    return wait_s if wait_s <= HOLD_MAX_S else None
