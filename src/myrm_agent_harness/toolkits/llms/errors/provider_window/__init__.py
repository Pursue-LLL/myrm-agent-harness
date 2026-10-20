"""Provider rate-limit window: typed "when may I retry" fact and its extractor.

[INPUT]
- provider_window.extract, provider_window.types

[OUTPUT]
- ProviderWindowHint, WindowKind, WindowSource, IN_TURN_WAIT_MAX_S, HOLD_MAX_S
- extract_provider_window, has_rejected_quota_window
- deferral_wait_s

[POS]
Facade for the provider-window subpackage; consumers import from here only.
"""

from .deferral import deferral_wait_s
from .extract import extract_provider_window, has_rejected_quota_window
from .types import (
    HOLD_MAX_S,
    IN_TURN_WAIT_MAX_S,
    ProviderWindowHint,
    WindowKind,
    WindowSource,
)

__all__ = [
    "HOLD_MAX_S",
    "IN_TURN_WAIT_MAX_S",
    "ProviderWindowHint",
    "WindowKind",
    "WindowSource",
    "deferral_wait_s",
    "extract_provider_window",
    "has_rejected_quota_window",
]
