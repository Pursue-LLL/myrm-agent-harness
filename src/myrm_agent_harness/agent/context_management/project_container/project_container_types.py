"""强类型契约定义：统一项目全生命周期资产容器、会话物理拖拽归档与零噪音静默收纳套件。

[INPUT]
- 无外部动态依赖，定义会话生命周期可见性、资产类别、拖拽归纳事件与项目工作区容器契约。

[OUTPUT]
- SessionVisibilityStatus: 会话生命周期可见性枚举 (活跃主栏 / 静默归档 / 保险箱封存)
- ProjectAssetKind: 项目资产类别枚举 (会话 / 工件 / 里程碑 / 看板任务 / 挂载卷)
- ProjectAssetItem: 统一项目资产项契约
- DragDropIngestionEvent: 侧边栏 HTML5 拖拽收纳事件契约
- SilentArchivingResult: 静默收纳与恢复操作结果契约
- ProjectContainerWorkspace: 统一项目真实资产容器契约

[POS]
- 位于 context_management/project_container/project_container_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum


class SessionVisibilityStatus(StrEnum):
    """会话生命周期可见性状态。"""

    ACTIVE_PRIMARY = "active_primary"
    SILENT_ARCHIVED = "silent_archived"
    PERMANENT_VAULT = "permanent_vault"


class ProjectAssetKind(StrEnum):
    """项目聚合资产类型。"""

    CONVERSATION_SESSION = "conversation_session"
    COMPILED_ARTIFACT = "compiled_artifact"
    DELIVERABLE_MILESTONE = "deliverable_milestone"
    KANBAN_TASK = "kanban_task"
    WORKSPACE_VOLUME = "workspace_volume"


@dataclass(frozen=True)
class ProjectAssetItem:
    """项目统一资产条目契约。"""

    asset_id: str
    asset_kind: ProjectAssetKind
    title: str
    resource_uri: str
    visibility: SessionVisibilityStatus = SessionVisibilityStatus.ACTIVE_PRIMARY
    tags: tuple[str, ...] = field(default_factory=tuple)
    created_at_iso: str = ""
    updated_at_iso: str = ""


@dataclass(frozen=True)
class DragDropIngestionEvent:
    """侧边栏 HTML5 拖拽会话归入项目芯片事件契约。"""

    source_session_id: str
    target_project_id: str
    session_title: str = ""
    client_drag_type: str = "application/x-myrm-session"
    operator_user_id: str = "default_user"
    timestamp_iso: str = ""


@dataclass(frozen=True)
class SilentArchivingResult:
    """非活跃会话静默隐藏或恢复操作结果契约。"""

    session_id: str
    project_id: str
    previous_status: SessionVisibilityStatus
    current_status: SessionVisibilityStatus
    success: bool
    message: str


@dataclass(frozen=True)
class ProjectContainerWorkspace:
    """统一项目真实资产容器大盘契约。"""

    project_id: str
    project_name: str
    description: str
    assets: tuple[ProjectAssetItem, ...]
    active_session_ids: tuple[str, ...]
    archived_session_ids: tuple[str, ...]
    milestone_count: int
    artifact_count: int
    total_asset_count: int
    updated_at_iso: str
