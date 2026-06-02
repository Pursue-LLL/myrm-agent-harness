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
        self.ui_artifacts.append(ui)

    def add_data_update(self, update: UIDataUpdate) -> None:
        """添加数据增量更新"""
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
