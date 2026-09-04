"""Browser task space management for concurrent and isolated subagent operations."""

from .space_manager import HarnessTaskSpaceManager
from .task_space import BrowserTaskSpace

__all__ = [
    "BrowserTaskSpace",
    "HarnessTaskSpaceManager",
]
