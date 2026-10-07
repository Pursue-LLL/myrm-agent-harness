"""核心引擎实现：统一项目全生命周期资产容器、会话物理拖拽归档与零噪音静默收纳。

[INPUT]
- 依赖 project_container_types.py 中的契约，标准库 datetime 等。

[OUTPUT]
- UnifiedProjectContainerEngine: 统一项目资产容器与拖拽归档引擎

[POS]
- 位于 context_management/project_container/unified_project_container_engine.py
"""

from datetime import datetime, timezone
from typing import Sequence

from .project_container_types import (
    DragDropIngestionEvent,
    ProjectAssetItem,
    ProjectAssetKind,
    ProjectContainerWorkspace,
    SessionVisibilityStatus,
    SilentArchivingResult,
)


class UnifiedProjectContainerEngine:
    """统一项目资产容器与拖拽归档引擎。

    彻底破除知识工作者在跨数周推进复杂工作时因数十个子会话散落侧边栏翻找极度困难、
    多类型工作任务割裂管理、以及已完成/不活跃会话无限堆叠导致侧边栏变成垃圾场的混乱痛点。
    """

    def __init__(self) -> None:
        # 内存态项目元数据: project_id -> { "name": str, "description": str }
        self._project_metadata: dict[str, dict[str, str]] = {}
        # 资产注册表: project_id -> dict[asset_id, ProjectAssetItem]
        self._project_assets: dict[str, dict[str, ProjectAssetItem]] = {}
        # 会话与项目反向映射: session_id -> project_id
        self._session_project_index: dict[str, str] = {}

    def register_or_update_project(
        self,
        project_id: str,
        name: str,
        description: str = "",
    ) -> ProjectContainerWorkspace:
        """注册或更新项目基础元数据并返回当前聚合工作区容器。"""
        self._project_metadata[project_id] = {
            "name": name,
            "description": description,
        }
        if project_id not in self._project_assets:
            self._project_assets[project_id] = {}
        return self.consolidate_project_assets(project_id)

    def ingest_session_via_drag_drop(
        self,
        event: DragDropIngestionEvent,
    ) -> ProjectContainerWorkspace:
        """通过侧边栏 HTML5 拖拽事件将会话原子化吸纳进目标项目容器。"""
        target_pid = event.target_project_id
        if target_pid not in self._project_metadata:
            # 自动登记目标项目（若尚未登记）
            self.register_or_update_project(
                project_id=target_pid,
                name=f"Project {target_pid}",
                description="Auto-registered container from drag-and-drop ingestion",
            )

        sid = event.source_session_id
        # 若此前已归属于其它项目，从旧项目中解绑以保证单一归属与零混乱
        old_pid = self._session_project_index.get(sid)
        if old_pid and old_pid != target_pid:
            if old_pid in self._project_assets and sid in self._project_assets[old_pid]:
                del self._project_assets[old_pid][sid]

        now_iso = datetime.now(timezone.utc).isoformat()
        title = event.session_title if event.session_title else f"Session {sid}"

        asset_item = ProjectAssetItem(
            asset_id=sid,
            asset_kind=ProjectAssetKind.CONVERSATION_SESSION,
            title=title,
            resource_uri=f"session://{sid}",
            visibility=SessionVisibilityStatus.ACTIVE_PRIMARY,
            tags=("drag_dropped",),
            created_at_iso=now_iso,
            updated_at_iso=now_iso,
        )

        self._project_assets[target_pid][sid] = asset_item
        self._session_project_index[sid] = target_pid

        return self.consolidate_project_assets(target_pid)

    def attach_asset(
        self,
        project_id: str,
        asset: ProjectAssetItem,
    ) -> ProjectContainerWorkspace:
        """向项目容器中挂载专业工件、交付里程碑或任务。"""
        if project_id not in self._project_metadata:
            self.register_or_update_project(project_id, f"Project {project_id}")

        self._project_assets[project_id][asset.asset_id] = asset
        if asset.asset_kind == ProjectAssetKind.CONVERSATION_SESSION:
            self._session_project_index[asset.asset_id] = project_id

        return self.consolidate_project_assets(project_id)

    def toggle_session_silent_archiving(
        self,
        session_id: str,
        hide: bool = True,
        project_id: str | None = None,
    ) -> SilentArchivingResult:
        """单键静默归档隐藏会话或从归档抽屉一键唤醒恢复。"""
        resolved_pid = project_id or self._session_project_index.get(session_id)
        if not resolved_pid or resolved_pid not in self._project_assets:
            return SilentArchivingResult(
                session_id=session_id,
                project_id=resolved_pid or "unknown",
                previous_status=SessionVisibilityStatus.ACTIVE_PRIMARY,
                current_status=SessionVisibilityStatus.ACTIVE_PRIMARY,
                success=False,
                message=f"Session {session_id} not found in any registered project container.",
            )

        asset_map = self._project_assets[resolved_pid]
        current_asset = asset_map.get(session_id)
        if not current_asset:
            return SilentArchivingResult(
                session_id=session_id,
                project_id=resolved_pid,
                previous_status=SessionVisibilityStatus.ACTIVE_PRIMARY,
                current_status=SessionVisibilityStatus.ACTIVE_PRIMARY,
                success=False,
                message=f"Session asset {session_id} not registered in project {resolved_pid}.",
            )

        prev_status = current_asset.visibility
        new_status = (
            SessionVisibilityStatus.SILENT_ARCHIVED
            if hide
            else SessionVisibilityStatus.ACTIVE_PRIMARY
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_asset = ProjectAssetItem(
            asset_id=current_asset.asset_id,
            asset_kind=current_asset.asset_kind,
            title=current_asset.title,
            resource_uri=current_asset.resource_uri,
            visibility=new_status,
            tags=current_asset.tags,
            created_at_iso=current_asset.created_at_iso,
            updated_at_iso=now_iso,
        )
        asset_map[session_id] = updated_asset

        action_msg = "silently archived and hidden" if hide else "restored to primary sidebar"
        return SilentArchivingResult(
            session_id=session_id,
            project_id=resolved_pid,
            previous_status=prev_status,
            current_status=new_status,
            success=True,
            message=f"Session {session_id} successfully {action_msg}.",
        )

    def consolidate_project_assets(
        self,
        project_id: str,
    ) -> ProjectContainerWorkspace:
        """聚合计算项目全要素资产，输出容器完整视图。"""
        meta = self._project_metadata.get(
            project_id,
            {"name": f"Project {project_id}", "description": ""},
        )
        asset_map = self._project_assets.get(project_id, {})

        all_assets: list[ProjectAssetItem] = list(asset_map.values())
        active_sessions: list[str] = []
        archived_sessions: list[str] = []
        milestone_count = 0
        artifact_count = 0

        for item in all_assets:
            if item.asset_kind == ProjectAssetKind.CONVERSATION_SESSION:
                if item.visibility == SessionVisibilityStatus.ACTIVE_PRIMARY:
                    active_sessions.append(item.asset_id)
                elif item.visibility == SessionVisibilityStatus.SILENT_ARCHIVED:
                    archived_sessions.append(item.asset_id)
            elif item.asset_kind == ProjectAssetKind.DELIVERABLE_MILESTONE:
                milestone_count += 1
            elif item.asset_kind == ProjectAssetKind.COMPILED_ARTIFACT:
                artifact_count += 1

        now_iso = datetime.now(timezone.utc).isoformat()
        return ProjectContainerWorkspace(
            project_id=project_id,
            project_name=meta["name"],
            description=meta["description"],
            assets=tuple(all_assets),
            active_session_ids=tuple(active_sessions),
            archived_session_ids=tuple(archived_sessions),
            milestone_count=milestone_count,
            artifact_count=artifact_count,
            total_asset_count=len(all_assets),
            updated_at_iso=now_iso,
        )

    def get_project_for_session(self, session_id: str) -> str | None:
        """获取指定会话归属的项目 ID。"""
        return self._session_project_index.get(session_id)
