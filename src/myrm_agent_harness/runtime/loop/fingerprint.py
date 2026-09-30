"""Semantic fingerprint extractor and anomaly detector for adaptive loop pacing.

[INPUT]
- Raw LLM response string from an inspection turn

[OUTPUT]
- Canonical SHA-256 digest with dynamic clock/duration/iteration noise stripped
- Boolean alert flag for urgent anomalies requiring instant floor reset

[POS]
Harness runtime layer. Defends against measurement decay where clock drift
would otherwise defeat exponential backoff.
"""

from __future__ import annotations

import hashlib
import re

# Severe anomaly keywords that force instant backoff reset to floor
_CRITICAL_ALERT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(fatal|panic|oom|out of memory|segmentation fault)\b", re.IGNORECASE),
    re.compile(r"\b(exit code [1-9]\d*|status code [45]\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(build failed|test failed|compilation error)\b", re.IGNORECASE),
    re.compile(r"traceback \(most recent call last\)", re.IGNORECASE),
    re.compile(r"\bexception\b", re.IGNORECASE),
)

# Regex normalizers for temporal & dynamic noise
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CHECKED_AT_PREFIX_RE = re.compile(
    r"\b(checked at|checked on|verified at|inspected at|检查时间|巡检时间|当前时间)\b",
    re.IGNORECASE,
)
_TIME_STAMP_RE = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?(\.\d+)?\b")
_DATE_STAMP_RE = re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b")
_DURATION_RE = re.compile(
    r"\b\d+(\.\d+)?\s*(ms|s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)\b",
    re.IGNORECASE,
)
_ITERATION_NOISE_RE = re.compile(
    r"(\[/?loop wakeup #\d+[^\]]*\]|第\s*\d+\s*(次|轮)(巡检|检查)?|iteration\s*#?\d+)",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")


def has_alert_anomaly(response: str) -> bool:
    """Check if response contains critical error signals requiring instant alert reset."""
    if not response:
        return False
    return any(pattern.search(response) is not None for pattern in _CRITICAL_ALERT_PATTERNS)


def extract_semantic_fingerprint(response: str) -> str:
    """Compute canonical SHA-256 fingerprint with transient noise stripped.

    Strips:
    - ANSI terminal color codes
    - Dates, timestamps, execution durations
    - Injected wakeup headers and iteration counters
    - Normalizes surrounding whitespace to prevent spurious jitter
    """
    if not response:
        return ""

    text = _ANSI_ESCAPE_RE.sub("", response)
    text = _ITERATION_NOISE_RE.sub("", text)
    text = _CHECKED_AT_PREFIX_RE.sub("", text)
    text = _DATE_STAMP_RE.sub("", text)
    text = _TIME_STAMP_RE.sub("", text)
    text = _DURATION_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip().lower()

    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
