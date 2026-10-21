"""Browser task space management for concurrent and isolated subagent operations.

[INPUT]
- .space_manager::HarnessTaskSpaceManager (POS: 任务空间管理器)
- .task_space::BrowserTaskSpace (POS: 任务空间实体)

[OUTPUT]
- BrowserTaskSpace: 任务空间实体
- HarnessTaskSpaceManager: 任务空间管理器

[POS]
浏览器任务空间子包入口门面。暴露 BrowserTaskSpace 与 HarnessTaskSpaceManager 核心类。
"""

from .space_manager import HarnessTaskSpaceManager
from .task_space import BrowserTaskSpace

__all__ = [
    "BrowserTaskSpace",
    "HarnessTaskSpaceManager",
]
