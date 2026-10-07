"""Multi-Bot Shared Group Infinite Ping-Pong Chatter Governor.

Provides turn watchdog enforcement, pre-flight incremental cognitive value
introspection, turn mutex arbitration, and emergency braking for multi-bot shared groups.
"""

from .multibot_chatter_governor import (
    GroupTurnArbitrator,
    IncrementalCognitiveValueEvaluator,
    MultiBotChatterGovernor,
)
from .multibot_governor_types import (
    BotTurnEvent,
    CognitiveValueEvaluation,
    GovernorAction,
    GovernorDecision,
    MessageSenderRole,
    MultiBotGovernorConfig,
    MutexAcquireResult,
)

__all__ = [
    "BotTurnEvent",
    "CognitiveValueEvaluation",
    "GovernorAction",
    "GovernorDecision",
    "GroupTurnArbitrator",
    "IncrementalCognitiveValueEvaluator",
    "MessageSenderRole",
    "MultiBotChatterGovernor",
    "MultiBotGovernorConfig",
    "MutexAcquireResult",
]
