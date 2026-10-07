"""Task Triad Trajectory and Anti-Loop Execution Blackbox suite.

[INPUT]
- Internal: types, ledger, injector, manager

[OUTPUT]
- TriadMilestone, TriadFailedAttempt, TriadUserSteering, TaskTriadBlackboxTrajectory
- AntiLoopPromptSnapshot, TrajectoryTaskStatus
- TriadStateLedger, AntiLoopPromptInjector, TaskTriadTrajectoryManager

[POS]
Harness framework layer for GPT-6 Astra-inspired long-horizon task execution memory.
"""

from .injector import AntiLoopPromptInjector
from .ledger import TriadStateLedger
from .manager import TaskTriadTrajectoryManager
from .types import (
    AntiLoopPromptSnapshot,
    TaskTriadBlackboxTrajectory,
    TrajectoryTaskStatus,
    TriadFailedAttempt,
    TriadMilestone,
    TriadUserSteering,
)

__all__ = [
    "AntiLoopPromptInjector",
    "AntiLoopPromptSnapshot",
    "TaskTriadBlackboxTrajectory",
    "TaskTriadTrajectoryManager",
    "TrajectoryTaskStatus",
    "TriadFailedAttempt",
    "TriadMilestone",
    "TriadStateLedger",
    "TriadUserSteering",
]
