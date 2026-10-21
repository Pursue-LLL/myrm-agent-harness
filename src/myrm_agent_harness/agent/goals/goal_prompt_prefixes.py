"""Goal prompt prefix constants — SSOT for continuation and focus skip detection.

[INPUT]
- None (leaf constants module)

[OUTPUT]
- GOAL_CONTINUATION_PREFIX: Prefix for auto-continue goal prompts
- GOAL_WRAPUP_PREFIX: Prefix for budget wrap-up goal prompts

[POS]
Shared string prefixes used by audit prompt builders and goal_focus_middleware
skip detection. Kept in a leaf module to avoid audit ↔ continuation cycles.
"""

from __future__ import annotations

GOAL_CONTINUATION_PREFIX = "[Continuing toward your standing goal]"
GOAL_WRAPUP_PREFIX = "[Budget reached — wrap-up turn]"

__all__ = ["GOAL_CONTINUATION_PREFIX", "GOAL_WRAPUP_PREFIX"]
