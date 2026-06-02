"""ArtifactTracker 观察者

负责记录文件操作到 ArtifactTracker。

[INPUT]
- agent.context_management.tracking.artifact_tracker::ArtifactAction (POS: Artifact Trail  Agent  Factory Research)

[OUTPUT]
- TrackerObserver: class — Tracker Observer

[POS]
Provides TrackerObserver.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import FileOperationObserver

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class TrackerObserver(FileOperationObserver):
    """ArtifactTracker 观察者

    记录文件操作到 ArtifactTracker，支持文件生命周期管理。
    """

    async def on_file_created(self, path: str, content: str) -> None:
        """文件创建事件"""
        self._record_artifact(path, "CREATED", "Created new file")

    async def on_file_modified(self, path: str, old_content: str, new_content: str) -> None:
        """文件修改事件"""
        self._record_artifact(path, "MODIFIED", "Modified file")

    async def on_file_viewed(self, path: str) -> None:
        """文件查看事件

        Records file access for context files to support lifecycle management.
        """
        try:
            from myrm_agent_harness.runtime.execution_paths import track_context_file_access_if_needed

            await track_context_file_access_if_needed(path)
        except Exception:
            pass

    def _record_artifact(self, path: str, action: str, description: str) -> None:
        """记录文件操作到 ArtifactTracker

        静默失败，不影响工具正常执行。

        Args:
            path: 文件路径
            action: 操作类型
            description: 操作描述
        """
        try:
            from myrm_agent_harness.agent.context_management.infra.session_lock import get_current_chat_id
            from myrm_agent_harness.agent.context_management.tracking.artifact_tracker import (
                ArtifactAction,
                get_or_create_artifact_tracker,
            )

            chat_id = get_current_chat_id()
            if chat_id:
                tracker = get_or_create_artifact_tracker(chat_id)
                tracker.record(
                    path=path, action=ArtifactAction[action], tool_name="text_editor_tool", description=description
                )
        except Exception as e:
            # 静默失败，不影响工具正常执行
            logger.debug(f"Failed to record artifact: {e}")
