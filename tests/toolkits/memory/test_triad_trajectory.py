"""Unit tests for Long-Horizon Task Triad State Trajectory and Anti-Loop Blackbox suite."""

import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.memory.triad_trajectory import (
    AntiLoopPromptInjector,
    TaskTriadTrajectoryManager,
    TrajectoryTaskStatus,
    TriadStateLedger,
)


def test_triad_state_ledger_records_and_versions():
    """Verify recording of milestones, dead ends, and user steerings with version increments."""
    ledger = TriadStateLedger(
        task_id="task_refactor_101",
        session_id="sess_alpha",
        initial_goal="全面重构认证模块为 JWT 无状态认证",
    )
    assert ledger.version == 1
    assert len(ledger.milestones) == 0
    assert len(ledger.failed_attempts) == 0
    assert len(ledger.active_steerings) == 0

    # 1. Record milestone
    ms = ledger.record_milestone(
        step_index=2,
        title="完成密码哈希与 Argon2 升级",
        verified_output_summary="单元测试 12 项全部通过，哈希耗时 120ms",
        description="移除了旧的 sha256 存储",
        artifacts=["src/auth/hash.py"],
    )
    assert ms.step_index == 2
    assert ledger.version == 2
    assert len(ledger.milestones) == 1

    # 2. Record failed attempt (dead end)
    fa = ledger.record_failed_attempt(
        step_index=4,
        action_attempted="docker run -p 8080:8080 auth-service",
        error_type="PortConflict",
        error_summary="端口 8080 已被宿主机占用导致容器启动失败",
        dead_end_pattern="8080:8080",
        prohibited_rule="严禁再尝试绑定 8080 端口，必须使用 8081 或动态端口",
        lessons_learned="先通过 lsof -i :8080 检查端口占用情况",
    )
    assert fa.step_index == 4
    assert ledger.version == 3
    assert len(ledger.failed_attempts) == 1

    # 3. Record in-flight steering
    st = ledger.record_user_steering(
        turn_index=5,
        instruction_raw="注意不要引入任何三方 Redis 依赖，全部使用纯内存缓存",
        distilled_constraint="禁止引入三方 Redis 依赖，必须使用内存缓存",
        scope="global",
    )
    assert st.is_active is True
    assert ledger.version == 4
    assert len(ledger.active_steerings) == 1

    # 4. Deactivate steering
    assert ledger.deactivate_steering(st.steering_id) is True
    assert len(ledger.active_steerings) == 0
    assert ledger.version == 5


def test_dead_end_pattern_matching_prohibition():
    """Verify dead-end path matching prevents repeating catastrophic failures."""
    ledger = TriadStateLedger(
        task_id="task_debug_202",
        session_id="sess_beta",
        initial_goal="排查数据库死锁问题",
    )

    ledger.record_failed_attempt(
        step_index=1,
        action_attempted="systemctl restart postgresql",
        error_type="PermissionDenied",
        error_summary="无 root 权限重启系统服务",
        dead_end_pattern="systemctl restart",
        prohibited_rule="不要调用 systemctl restart，无 sudo 权限",
    )

    ledger.record_failed_attempt(
        step_index=3,
        action_attempted="pytest tests/e2e/test_long.py --timeout=5",
        error_type="Timeout",
        error_summary="5s 发生超时，端到端测试需要至少 30s",
        dead_end_pattern=r"--timeout=[0-9]\b",
        prohibited_rule="禁止设置小于 10s 的端到端测试超时",
    )

    # Substring / command match
    prohibited, attempt = ledger.check_action_prohibited("sudo systemctl restart postgresql")
    assert prohibited is True
    assert attempt is not None
    assert attempt.error_type == "PermissionDenied"

    # Regex pattern match
    prohibited_re, attempt_re = ledger.check_action_prohibited("pytest tests/e2e/test_long.py --timeout=3")
    assert prohibited_re is True
    assert attempt_re is not None
    assert attempt_re.error_type == "Timeout"

    # Safe command passes
    safe, safe_att = ledger.check_action_prohibited("pytest tests/unit/test_auth.py")
    assert safe is False
    assert safe_att is None


def test_anti_loop_prompt_injector_budgeting():
    """Verify compact prompt snapshot synthesis adheres to token budgets."""
    ledger = TriadStateLedger(
        task_id="task_migration_303",
        session_id="sess_gamma",
        initial_goal="迁移前端到 React 19 并清理废弃 Hook",
    )

    ledger.record_milestone(
        step_index=1,
        title="升级 package.json 并跑通构建",
        verified_output_summary="bun run build 成功，0 错误",
    )

    for i in range(5):
        ledger.record_failed_attempt(
            step_index=i + 2,
            action_attempted=f"npm install legacy-pkg-{i}",
            error_type="DependencyConflict",
            error_summary=f"包 legacy-pkg-{i} 不兼容 React 19 peer deps",
            dead_end_pattern=f"legacy-pkg-{i}",
            prohibited_rule=f"禁止安装 legacy-pkg-{i}",
        )

    ledger.record_user_steering(
        turn_index=3,
        instruction_raw="用户在第 3 轮追加：请不要修改 src/legacy/ 目录下的任何文件！",
        distilled_constraint="禁止修改 src/legacy/ 目录下文件",
    )

    snapshot = AntiLoopPromptInjector.build_snapshot(ledger, step_hint="legacy-pkg", max_tokens=150)

    assert snapshot.task_id == "task_migration_303"
    assert snapshot.latest_milestone_title == "升级 package.json 并跑通构建"
    assert len(snapshot.active_user_steerings_injected) == 1
    assert len(snapshot.dead_end_rules_injected) >= 1
    assert "<task_triad_blackbox" in snapshot.formatted_prompt_block
    assert "禁止修改 src/legacy/" in snapshot.formatted_prompt_block
    assert snapshot.snapshot_token_estimate <= 160


def test_task_triad_trajectory_manager_persistence_and_handoff():
    """Verify task trajectory persistence to storage volume and lossless handoff recovery."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = TaskTriadTrajectoryManager(persistence_dir=tmp_dir)

        ledger = manager.get_or_create_ledger(
            task_id="task_cloud_404",
            session_id="sess_cloud",
            initial_goal="部署 Cloudflare Worker 微服务",
        )

        ledger.record_milestone(
            step_index=1,
            title="初始化 wrangler.jsonc",
            verified_output_summary="配置文件验证成功",
        )

        ledger.record_failed_attempt(
            step_index=2,
            action_attempted="wrangler deploy --env production",
            error_type="AuthError",
            error_summary="缺少 CLOUDFLARE_API_TOKEN 凭证",
            dead_end_pattern="wrangler deploy --env production",
            prohibited_rule="未配置环境变量前禁止直接向 production 发布",
        )

        ledger.record_user_steering(
            turn_index=2,
            instruction_raw="先发布到 staging 环境测试",
            distilled_constraint="发布目标锁定为 staging",
        )

        # Export to volume
        exported = manager.export_trajectory("task_cloud_404")
        assert exported.task_id == "task_cloud_404"
        assert len(exported.milestones) == 1
        assert len(exported.failed_attempts) == 1
        assert len(exported.user_steerings) == 1

        json_file = Path(tmp_dir) / "task_blackbox_task_cloud_404.json"
        assert json_file.exists()

        # Simulate crash / handoff to a fresh manager instance
        fresh_manager = TaskTriadTrajectoryManager(persistence_dir=tmp_dir)
        recovered_ledger = fresh_manager.get_or_create_ledger(
            task_id="task_cloud_404",
            session_id="sess_cloud",
            initial_goal="部署 Cloudflare Worker 微服务",
        )

        assert recovered_ledger.version == ledger.version
        assert len(recovered_ledger.milestones) == 1
        assert recovered_ledger.milestones[0].title == "初始化 wrangler.jsonc"
        assert len(recovered_ledger.failed_attempts) == 1
        assert len(recovered_ledger.active_steerings) == 1

        # Check action prohibition on recovered ledger
        prohibited, _ = fresh_manager.check_action_prohibited(
            "task_cloud_404",
            "wrangler deploy --env production",
        )
        assert prohibited is True

        fresh_manager.mark_task_status("task_cloud_404", TrajectoryTaskStatus.COMPLETED)
        assert fresh_manager.get_ledger("task_cloud_404").status == TrajectoryTaskStatus.COMPLETED
