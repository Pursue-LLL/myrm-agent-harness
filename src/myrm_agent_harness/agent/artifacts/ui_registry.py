"""UI 工件注册表

用于收集 Agent 执行过程中生成的 UI 工件。

[INPUT]
- (none)

[OUTPUT]
- UIRegistry: class — U I Registry
- get_ui_registry: Returns:

[POS]
Provides UIRegistry, get_ui_registry.
"""

from dataclasses import dataclass, field

from .ui_artifact import UIArtifact, UIDataUpdate

# Cross-task UI events: StreamExecutor runs in asyncio.create_task(), so tool calls
# mutate a child ContextVar copy. Parent post_run must collect by message_id.
_PENDING_BY_MESSAGE_ID: dict[str, list[UIArtifact | UIDataUpdate]] = {}

# Process-scoped fallback when ContextVars do not propagate into LangGraph tool tasks.
_RUN_MESSAGE_ID_BY_SESSION: dict[str, str] = {}
_CURRENT_RUN_UI_MESSAGE_ID: str | None = None


def bind_run_message_id(session_key: str, message_id: str) -> None:
    """Bind assistant message id to a session for cross-task UI delivery."""
    global _CURRENT_RUN_UI_MESSAGE_ID
    _CURRENT_RUN_UI_MESSAGE_ID = message_id
    if session_key:
        _RUN_MESSAGE_ID_BY_SESSION[session_key] = message_id


def pop_run_message_id(session_key: str) -> None:
    """Clear process-scoped message binding after a run completes."""
    global _CURRENT_RUN_UI_MESSAGE_ID
    _CURRENT_RUN_UI_MESSAGE_ID = None
    if session_key:
        _RUN_MESSAGE_ID_BY_SESSION.pop(session_key, None)


def _resolve_stash_message_id() -> str | None:
    """Resolve message_id for cross-task UI stash (artifact ctx or bound turn id)."""
    from .context import get_artifact_context

    ctx = get_artifact_context()
    if ctx is not None and ctx.message_id:
        return ctx.message_id

    try:
        from myrm_agent_harness.agent.middlewares._session_context import (
            get_active_message_id,
        )

        active_message_id = get_active_message_id()
        if active_message_id:
            return active_message_id
    except Exception:
        pass

    global _CURRENT_RUN_UI_MESSAGE_ID
    if _CURRENT_RUN_UI_MESSAGE_ID:
        return _CURRENT_RUN_UI_MESSAGE_ID

    try:
        from myrm_agent_harness.agent.middlewares._session_context import get_approval_session

        session_key = get_approval_session()
        if session_key:
            bound = _RUN_MESSAGE_ID_BY_SESSION.get(session_key)
            if bound:
                return bound
    except Exception:
        pass

    try:
        from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
            get_bound_message_id,
        )

        return get_bound_message_id()
    except Exception:
        return None


def pop_pending_ui_events_for_message(message_id: str) -> list[UIArtifact | UIDataUpdate]:
    """Pop UI events stashed for a message (cross-task safe)."""
    return _PENDING_BY_MESSAGE_ID.pop(message_id, [])


def has_pending_ui_events_for_message(message_id: str) -> bool:
    """True when either in-process registry or message stash has pending UI events."""
    from .context import get_artifact_context

    ctx = get_artifact_context()
    if ctx is not None and ctx.ui_registry.has_pending_events():
        return True
    return bool(_PENDING_BY_MESSAGE_ID.get(message_id))


def register_ui_artifact(ui: UIArtifact) -> bool:
    """Register a UI artifact for SSE/post_run delivery.

    Returns False when no message_id is available (fail-closed).
    """
    registry = get_ui_registry()
    if registry is not None:
        registry.add_ui(ui)
        return True

    message_id = _resolve_stash_message_id()
    if not message_id:
        return False

    _PENDING_BY_MESSAGE_ID.setdefault(message_id, []).append(ui)
    return True


@dataclass
class UIRegistry:
    """UI 工件注册表

    收集 Agent 工具调用期间生成的 UI 工件和数据更新。
    每个请求应该有自己的注册表实例。
    """

    # 完整 UI 工件列表（新创建的 UI）
    ui_artifacts: list[UIArtifact] = field(default_factory=list)

    # 数据增量更新列表
    data_updates: list[UIDataUpdate] = field(default_factory=list)

    def add_ui(self, ui: UIArtifact) -> None:
        """添加 UI 工件"""
        message_id = _resolve_stash_message_id()
        if message_id:
            _PENDING_BY_MESSAGE_ID.setdefault(message_id, []).append(ui)
            return
        self.ui_artifacts.append(ui)

    def add_data_update(self, update: UIDataUpdate) -> None:
        """添加数据增量更新"""
        message_id = _resolve_stash_message_id()
        if message_id:
            _PENDING_BY_MESSAGE_ID.setdefault(message_id, []).append(update)
            return
        self.data_updates.append(update)

    def pop_pending_events(self) -> list[UIArtifact | UIDataUpdate]:
        """弹出所有待发送的事件（消费后清空）

        Returns:
            待发送的 UI 事件列表
        """
        events: list[UIArtifact | UIDataUpdate] = []
        events.extend(self.ui_artifacts)
        events.extend(self.data_updates)

        # 清空
        self.ui_artifacts = []
        self.data_updates = []

        return events

    def has_pending_events(self) -> bool:
        """检查是否有待发送的事件"""
        return bool(self.ui_artifacts) or bool(self.data_updates)

    def clear(self) -> None:
        """清空所有事件"""
        self.ui_artifacts.clear()
        self.data_updates.clear()


def get_ui_registry() -> UIRegistry | None:
    """获取当前请求的 UI 注册表

    从统一的 ArtifactContext 获取。

    Returns:
        UI 注册表，如果未初始化则返回 None
    """
    from .context import get_artifact_context

    ctx = get_artifact_context()
    if ctx is not None:
        return ctx.ui_registry
    return None
