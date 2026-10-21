"""Artifact 事件处理

[INPUT]
- agent.artifacts::ArtifactRegistry, InlineArtifactQueue, RealtimeContentQueue (POS: 文件/内联/实时内容注册表)
- toolkits.code_execution.executors.base::get_executor (POS: 沙箱文件读取句柄)

[OUTPUT]
- emit_artifacts_ready_event(): 发出 artifacts_ready 事件（懒加载，业务层按需读取）
- emit_artifact_focus_event(): 发出 artifact_focus 事件（主交付物聚焦）
- collect_inline_artifacts(): 收集工具执行中产生的内联 artifact（如图片 URL）
- process_realtime_content_events(): 处理实时内容更新事件

[POS]
Artifact event handler. Collects and emits file artifacts, inline artifacts, and real-time content events.

"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from myrm_agent_harness.agent.artifacts import (
    get_artifact_registry,
    get_inline_artifact_queue,
    get_realtime_content_queue,
    infer_artifact_type,
)
from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .types import AgentEventType

logger = get_agent_logger(__name__)


async def emit_artifacts_ready_event(message_id: str, context: dict[str, object]) -> AsyncGenerator[dict[str, object]]:
    """发出 artifacts_ready 事件（懒加载设计）

    框架层只提供文件路径和读取方法，业务层按需读取和持久化。

    事件格式::

        {
            "type": "artifacts_ready",
            "data": [{"filename": "chart.png", "path": "/workspace/chart.png", "type": "image"}],
            "read_content": async_function,
            "message_id": "msg_123",
        }
    """
    executor = get_executor()
    if executor is None:
        logger.debug(" executor 未初始化，跳过 artifacts_ready 事件")
        return

    registry = get_artifact_registry()
    if not registry or len(registry) == 0:
        logger.debug(" 没有工件需要发送")
        return

    artifacts_data: list[dict[str, str]] = []
    from myrm_agent_harness.agent.artifacts.file_id_registry import lookup_short_file_id

    for f in registry.get_all_files():
        filename = Path(f.path).name
        artifact_type = infer_artifact_type(filename)
        entry: dict[str, str] = {
            "filename": filename,
            "path": f.path,
            "type": artifact_type.value,
        }
        short_file_id = lookup_short_file_id(f.path)
        if short_file_id:
            entry["short_file_id"] = short_file_id
        artifacts_data.append(entry)

    if not artifacts_data:
        return

    async def read_content(path: str) -> bytes:
        return await executor.read_file_bytes(path)

    logger.info(" Emitting artifacts_ready event: %d files", len(artifacts_data))
    yield {
        "type": AgentEventType.ARTIFACTS_READY.value,
        "data": artifacts_data,
        "read_content": read_content,
        "message_id": message_id,
    }


async def emit_artifact_focus_event(message_id: str) -> AsyncGenerator[dict[str, object]]:
    """Emit artifact_focus for the primary deliverable after a successful run."""
    registry = get_artifact_registry()
    if not registry or len(registry) == 0:
        return

    from myrm_agent_harness.agent.artifacts.file_id_registry import lookup_short_file_id

    focus_path: str | None = None
    focus_short_id: str | None = None
    for generated in reversed(registry.get_all_files()):
        path = generated.path
        short_id = lookup_short_file_id(path)
        if short_id:
            focus_path = path
            focus_short_id = short_id
            break

    if not focus_short_id:
        return

    logger.info("Emitting artifact_focus for %s", focus_short_id)
    yield {
        "type": AgentEventType.ARTIFACT_FOCUS.value,
        "data": {
            "short_file_id": focus_short_id,
            "path": focus_path,
        },
        "message_id": message_id,
    }


async def collect_inline_artifacts(message_id: str) -> AsyncGenerator[dict[str, object]]:
    """Collect inline artifacts pushed by tools (e.g. image URLs) and emit ARTIFACTS events."""
    queue = get_inline_artifact_queue()
    if queue is None or not queue.has_pending_events():
        return

    events = queue.pop_events()
    artifacts_data: list[dict[str, str | int | None]] = []
    for evt in events:
        artifacts_data.append(
            {
                "id": evt.artifact_id,
                "filename": evt.filename,
                "type": evt.artifact_type.value,
                "content_type": evt.content_type,
                "size": 0,
                "preview_url": evt.preview_url,
                "download_url": evt.preview_url,
            }
        )

    if artifacts_data:
        yield {
            "type": AgentEventType.ARTIFACTS.value,
            "data": artifacts_data,
            "messageId": message_id,
        }
        logger.warning(" Sent %d inline artifact(s)", len(artifacts_data))


async def process_realtime_content_events(message_id: str) -> AsyncGenerator[dict[str, object]]:
    """处理实时内容更新事件"""
    queue = get_realtime_content_queue()
    if queue is None or not queue.has_pending_events():
        return

    for event in queue.pop_events():
        yield {
            "type": AgentEventType.ARTIFACT_CONTENT.value,
            "subtype": "complete" if event.is_complete else "chunk",
            "artifactId": event.artifact_id,
            "filename": event.filename,
            "content": event.content,
            "artifactType": event.artifact_type,
            "language": event.language,
            "messageId": message_id,
        }
        logger.debug(" Sending live content event: %s", event.filename)
