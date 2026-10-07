"""统一项目全生命周期资产容器、会话物理拖拽归档与零噪音静默收纳套件。

导出的主要类与契约：
- UnifiedProjectContainerEngine: 统一项目资产容器与拖拽归档引擎
- ProjectContainerWorkspace: 统一项目真实资产容器契约
- ProjectAssetItem: 统一项目资产项契约
- ProjectAssetKind: 项目资产类别枚举
- SessionVisibilityStatus: 会话生命周期可见性枚举
- DragDropIngestionEvent: 侧边栏 HTML5 拖拽收纳事件契约
- SilentArchivingResult: 静默收纳与恢复操作结果契约

[INPUT]
- agent.context_management.project_container.project_container_types::DragDropIngestionEvent,
  ProjectAssetItem, ProjectAssetKind, ProjectContainerWorkspace, SessionVisibilityStatus,
  SilentArchivingResult (POS: 强类型契约定义：统一项目全生命周期资产容器、会话物理拖拽归档与零噪音静默收纳套件。)
- agent.context_management.project_container.unified_project_container_engine::UnifiedProjectContainerEngine
  (POS: 核心引擎实现：统一项目全生命周期资产容器、会话物理拖拽归档与零噪音静默收纳。)

[OUTPUT]
- Re-exports: DragDropIngestionEvent, ProjectAssetItem, ProjectAssetKind, ProjectContainerWorkspace,
  SessionVisibilityStatus, SilentArchivingResult, UnifiedProjectContainerEngine

[POS]
统一项目全生命周期资产容器、会话物理拖拽归档与零噪音静默收纳套件。
"""

from .project_container_types import (
    DragDropIngestionEvent,
    ProjectAssetItem,
    ProjectAssetKind,
    ProjectContainerWorkspace,
    SessionVisibilityStatus,
    SilentArchivingResult,
)
from .unified_project_container_engine import UnifiedProjectContainerEngine

__all__ = [
    "DragDropIngestionEvent",
    "ProjectAssetItem",
    "ProjectAssetKind",
    "ProjectContainerWorkspace",
    "SessionVisibilityStatus",
    "SilentArchivingResult",
    "UnifiedProjectContainerEngine",
]
