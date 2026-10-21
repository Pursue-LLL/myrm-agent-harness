"""Maintain mode taxonomy for wiki linter runs.

[INPUT]
- None (standalone enum definition)

[OUTPUT]
- MaintainMode: structural (zero LLM) vs full maintenance pipeline

[POS]
Single enum for cron REST maintain and manual Settings maintain SSOT.
"""

from __future__ import annotations

from enum import StrEnum


class MaintainMode(StrEnum):
    """Wiki maintenance intensity."""

    STRUCTURAL = "structural"
    FULL = "full"
