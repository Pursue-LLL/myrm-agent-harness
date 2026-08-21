"""Canonical tool error categories for structured error classification.

Unifies all tool-related error_category strings into a single StrEnum.
StrEnum values match the frontend i18n keys (progressSteps.errorCategories.*),
ensuring backend classification and frontend display stay in sync.

[INPUT]
- (none)

[OUTPUT]
- ToolErrorCategory: Canonical error category for tool execution and guard errors.

[POS]
Canonical tool error categories for structured error classification.
"""

from __future__ import annotations

from enum import StrEnum


from myrm_agent_harness.utils.errors import ToolErrorCategory

__all__ = ["ToolErrorCategory"]
