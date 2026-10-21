"""Multi-Bot Mention Focus & Anti-Thrash Compaction module (Item 42).

[INPUT]
- Viewport presence, focus signals, token usage metrics, and stream card heartbeats.

[OUTPUT]
- Unified public surface for multi-bot mention following, anti-thrash compaction decisions,
  and dead stream card cleanup.

[POS]
- Harness coordination layer public module interface for Item 42.
"""

from .focus_compactor import (
    MultiBotFocusAndCompactionGuard,
    MultiBotFocusError,
)
from .types import (
    BotFocusSnapshot,
    CompactionEvaluation,
    CompactionPolicy,
    StreamCardHeartbeat,
    StreamCardState,
)

__all__ = [
    "BotFocusSnapshot",
    "CompactionEvaluation",
    "CompactionPolicy",
    "MultiBotFocusAndCompactionGuard",
    "MultiBotFocusError",
    "StreamCardHeartbeat",
    "StreamCardState",
]
