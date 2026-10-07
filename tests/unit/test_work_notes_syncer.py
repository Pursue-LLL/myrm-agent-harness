from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.artifacts import (
    ProgressStep,
    StepExecutionStatus,
    SyncDirection,
    WorkNotesSnapshot,
    WorkspaceWorkNotesSyncer,
)


@pytest.fixture
def workspace_tmp(tmp_path: Path) -> Path:
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def test_sync_to_workspace_renders_markdown_and_sets_hash(workspace_tmp: Path) -> None:
    syncer = WorkspaceWorkNotesSyncer(workspace_tmp)

    initial_snapshot = WorkNotesSnapshot(
        goal="重构认证模块，支持 JWT 与 OAuth2 双通道",
        current_step_index=1,
        steps=[
            ProgressStep(step_index=0, description="搭建 JWT 签发与验证管道", status=StepExecutionStatus.COMPLETED),
            ProgressStep(step_index=1, description="实现 GitHub OAuth2 回调处理", status=StepExecutionStatus.IN_PROGRESS),
            ProgressStep(step_index=2, description="编写端到端认证测试", status=StepExecutionStatus.PENDING),
        ],
        key_findings=["JWT 密钥采用 HS256 算法", "OAuth2 回调需严格校验 state 参数防 CSRF"],
        disqualified_approaches=["禁止将 token 明文存入 localStorage", "切勿在 URL 查询参数中传递 access_token"],
        todos=["补充刷新令牌黑名单机制", "配置速率限制中间件"],
    )

    res = syncer.sync_to_workspace(initial_snapshot)

    assert res.success is True
    assert res.direction == SyncDirection.AGENT_TO_WORKSPACE
    assert res.snapshot.last_synced_hash is not None

    notes_file = syncer.notes_file_path
    progress_file = syncer.progress_file_path
    assert notes_file.exists()
    assert progress_file.exists()

    notes_content = notes_file.read_text(encoding="utf-8")
    assert "重构认证模块" in notes_content
    assert "JWT 密钥采用 HS256 算法" in notes_content
    assert "禁止将 token 明文存入 localStorage" in notes_content
    assert "补充刷新令牌黑名单机制" in notes_content

    progress_content = progress_file.read_text(encoding="utf-8")
    assert "- [x] 步骤 0: 搭建 JWT 签发与验证管道 (✅ 已完成)" in progress_content
    assert "- [/] 步骤 1: 实现 GitHub OAuth2 回调处理 (⏳ 进行中)" in progress_content
    assert "- [ ] 步骤 2: 编写端到端认证测试" in progress_content


def test_external_modification_detection_and_human_intervention_merge(
    workspace_tmp: Path,
) -> None:
    syncer = WorkspaceWorkNotesSyncer(workspace_tmp)

    snapshot = WorkNotesSnapshot(
        goal="优化数据库索引",
        current_step_index=0,
        steps=[
            ProgressStep(step_index=0, description="分析慢查询日志", status=StepExecutionStatus.IN_PROGRESS),
            ProgressStep(step_index=1, description="创建复合索引 idx_user_created_at", status=StepExecutionStatus.PENDING),
        ],
        key_findings=["慢查询主要集中在用户时间线接口"],
        disqualified_approaches=["不要无脑增加单列索引"],
        todos=["更新 EXPLAIN 报告"],
    )
    sync_res = syncer.sync_to_workspace(snapshot)
    synced_snapshot = sync_res.snapshot

    # Initially in sync
    assert syncer.check_workspace_modification(synced_snapshot.last_synced_hash) is False

    # Simulate Human editing PROGRESS.md directly in external IDE (marking step 0 completed)
    progress_text = syncer.progress_file_path.read_text(encoding="utf-8")
    modified_progress = progress_text.replace("- [/] 步骤 0:", "- [x] 步骤 0:")
    syncer.progress_file_path.write_text(modified_progress, encoding="utf-8")

    # Simulate Human appending a new finding and a new todo in WORK_NOTES.md
    notes_text = syncer.notes_file_path.read_text(encoding="utf-8")
    modified_notes = notes_text + "\n- [ ] 人类手动追加的待办：重启只读从库\n"
    syncer.notes_file_path.write_text(modified_notes, encoding="utf-8")

    # Now modification must be detected
    assert syncer.check_workspace_modification(synced_snapshot.last_synced_hash) is True

    # Sync back into agent memory
    pull_res = syncer.sync_from_workspace(synced_snapshot)
    assert pull_res.success is True
    assert pull_res.direction == SyncDirection.WORKSPACE_TO_AGENT
    assert pull_res.intervention_diff is not None
    assert pull_res.intervention_diff.modified is True
    assert 0 in pull_res.intervention_diff.steps_completed_by_human
    assert any("重启只读从库" in t for t in pull_res.intervention_diff.new_todos_added)

    # Merged snapshot checks
    merged = pull_res.snapshot
    assert merged.steps[0].status == StepExecutionStatus.COMPLETED
    assert any("重启只读从库" in t for t in merged.todos)


def test_hydrate_initial_snapshot_creates_and_loads(workspace_tmp: Path) -> None:
    syncer = WorkspaceWorkNotesSyncer(workspace_tmp)

    # 1. First hydration in empty workspace
    s1 = syncer.hydrate_initial_snapshot(fallback_goal="初始化全新项目目标")
    assert s1.goal == "初始化全新项目目标"
    assert syncer.notes_file_path.exists()
    assert syncer.progress_file_path.exists()

    # 2. Second hydration re-reads existing files
    s2 = syncer.hydrate_initial_snapshot(fallback_goal="不同目标不会覆盖现有文件")
    assert s2.goal == "初始化全新项目目标"
