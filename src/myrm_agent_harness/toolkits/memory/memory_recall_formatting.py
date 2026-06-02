"""Memory recall formatting helpers.

[INPUT]
- (none)

[OUTPUT]
- parse_time_bound: Parse recall time filters into UTC datetimes.
- memory_age_label: Human-readable age label for memory timestamps.
- is_stale: Staleness check for recalled factual memories.
- channel_label: Human-readable channel provenance label.

[POS]
Memory recall formatting helper. Keeps agent tool definitions focused on orchestration.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

_STALENESS_THRESHOLD_HOURS = 24
_RELATIVE_TIME_RE = re.compile(r"^(\d+)\s*(d|h|w|m|y)$", re.IGNORECASE)
_RELATIVE_UNITS: dict[str, int] = {"h": 3600, "d": 86400, "w": 604800, "m": 2592000, "y": 31536000}


def parse_time_bound(value: str | None) -> datetime | None:
    """Parse a time-bound string into a UTC datetime."""
    if not value:
        return None
    value = value.strip()
    match = _RELATIVE_TIME_RE.match(value)
    if match:
        amount = int(match.group(1))
        unit_seconds = _RELATIVE_UNITS.get(match.group(2).lower(), 86400)
        return datetime.now(UTC) - timedelta(seconds=amount * unit_seconds)
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def memory_age_label(created_at: datetime) -> str:
    """Human-readable age label for a memory timestamp."""
    days = max(0, (datetime.now(UTC) - created_at).days)
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    months = days // 30
    if months == 1:
        return "1 month ago"
    if months < 12:
        return f"{months} months ago"
    years = days // 365
    if years == 1:
        return "1 year ago"
    return f"{years} years ago"


def is_stale(created_at: datetime) -> bool:
    """Whether a memory exceeds the staleness threshold."""
    delta = datetime.now(UTC) - created_at
    return delta.total_seconds() > _STALENESS_THRESHOLD_HOURS * 3600


def channel_label(channel_id: str | None) -> str:
    """Human-readable provenance label for a channel id."""
    if not channel_id:
        return ""

    normalized = channel_id.strip().lower()
    aliases = {
        "telegram": "Telegram",
        "tg": "Telegram",
        "feishu": "Feishu",
        "lark": "Feishu",
        "web": "Web",
        "slack": "Slack",
        "discord": "Discord",
        "email": "Email",
    }
    display = aliases.get(normalized)
    if display is None:
        display = channel_id.replace("_", " ").replace("-", " ").title()
    return f"[from {display}] "
