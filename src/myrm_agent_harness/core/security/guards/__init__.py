"""Core security guards — SSRF protection, privacy tracking, and privacy fail-closed ladder.

[INPUT]
- .privacy_ladder (POS: Privacy fail closed ladder)
- .privacy_tracker (POS: Privacy tracker)

[OUTPUT]
- PrivacyFailClosedLadder, PrivacyTracker: security guards

[POS]
Core security guards exports.
"""

from .privacy_ladder import (
    PrivacyFailClosedLadder,
    PrivacyFailClosedViolationError,
    PrivacyLadderLevel,
    PrivacyLadderVerdict,
    PrivacyLadderViolationType,
    PrivacyScope,
)
from .privacy_tracker import (
    DetectionRecord,
    PrivacyTracker,
    get_pending_privacy_event,
    get_privacy_policy,
    get_privacy_tracker,
    reset_privacy_tracker,
    set_privacy_policy,
)

__all__ = [
    "DetectionRecord",
    "PrivacyFailClosedLadder",
    "PrivacyFailClosedViolationError",
    "PrivacyLadderLevel",
    "PrivacyLadderVerdict",
    "PrivacyLadderViolationType",
    "PrivacyPolicy",
    "PrivacyScope",
    "PrivacyTracker",
    "get_pending_privacy_event",
    "get_privacy_policy",
    "get_privacy_tracker",
    "reset_privacy_tracker",
    "set_privacy_policy",
]

