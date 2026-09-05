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
from .ssrf import (
    SSRFResult,
    SSRFSecurityError,
    SSRFVerdict,
    async_pin_url,
    async_validate_url_for_ssrf,
    check_url,
    is_internal_ip,
    resolve_and_check,
    validate_url_for_ssrf,
)
from .url_allowlist import URLAllowlistGuard

__all__ = [
    "DetectionRecord",
    "PrivacyFailClosedLadder",
    "PrivacyFailClosedViolationError",
    "PrivacyLadderLevel",
    "PrivacyLadderVerdict",
    "PrivacyLadderViolationType",
    "PrivacyScope",
    "PrivacyTracker",
    "SSRFResult",
    "SSRFSecurityError",
    "SSRFVerdict",
    "URLAllowlistGuard",
    "async_pin_url",
    "async_validate_url_for_ssrf",
    "check_url",
    "get_pending_privacy_event",
    "get_privacy_policy",
    "get_privacy_tracker",
    "is_internal_ip",
    "reset_privacy_tracker",
    "resolve_and_check",
    "set_privacy_policy",
    "validate_url_for_ssrf",
]

