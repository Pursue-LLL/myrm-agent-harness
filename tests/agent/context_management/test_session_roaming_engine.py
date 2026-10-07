"""跨设备会话实时漫游、团队协作接力与沙箱热镜像套件单元测试。

[INPUT]
- DeviceAgnosticSessionRoamingEngine, CollaborationRole, DevicePlatform, ExecutableTeamShareBundle, ForkAndContinueResult

[OUTPUT]
- 自动化验证多端断点时序同步防回退、环境变量安全脱敏封包、Fork & Continue 沙箱热镜像接力

[POS]
- 位于 tests/agent/context_management/test_session_roaming_engine.py
"""

from datetime import datetime, timezone, timedelta
import pytest

from myrm_agent_harness.agent.context_management.session_roaming import (
    CollaborationRole,
    DeviceAgnosticSessionRoamingEngine,
    DevicePlatform,
    ExecutableTeamShareBundle,
    ForkAndContinueResult,
    SessionRoamingBreakpoint,
)


def test_sync_roaming_breakpoint_monotonic_sequence() -> None:
    """测试跨设备漫游断点同步与防旧版本倒退单调序列号校验。"""
    engine = DeviceAgnosticSessionRoamingEngine()

    # 1. 移动端设备初次同步草稿与断点 (seq=1)
    bp1 = engine.sync_roaming_breakpoint(
        session_id="session_101",
        client_device_id="iphone_15_pro",
        platform=DevicePlatform.MOBILE,
        cursor_message_index=12,
        pending_draft_input="请帮我写一段单元测试代码",
        active_background_task_count=1,
        environment_snapshot={"THEME": "dark"},
        sequence_number=1,
    )
    assert bp1.cursor_message_index == 12
    assert bp1.pending_draft_input == "请帮我写一段单元测试代码"
    assert bp1.sequence_number == 1

    # 2. 办公室 Mac 设备继续推进会话 (seq=2)
    bp2 = engine.sync_roaming_breakpoint(
        session_id="session_101",
        client_device_id="macbook_m3_max",
        platform=DevicePlatform.MAC,
        cursor_message_index=18,
        pending_draft_input="",
        active_background_task_count=0,
        environment_snapshot={"THEME": "dark", "EDITOR": "cursor"},
        sequence_number=2,
    )
    assert bp2.cursor_message_index == 18
    assert bp2.platform == DevicePlatform.MAC
    assert bp2.sequence_number == 2

    # 3. 移动端网络延迟后发来旧包 (seq=1 <= 2) -> 应当被防倒退机制忽略，保持 bp2 的状态
    bp_ignored = engine.sync_roaming_breakpoint(
        session_id="session_101",
        client_device_id="iphone_15_pro",
        platform=DevicePlatform.MOBILE,
        cursor_message_index=12,
        pending_draft_input="旧草稿",
        active_background_task_count=1,
        environment_snapshot={"THEME": "dark"},
        sequence_number=1,
    )
    assert bp_ignored.sequence_number == 2
    assert bp_ignored.cursor_message_index == 18

    # 4. 获取最新断点
    latest = engine.get_roaming_breakpoint("session_101")
    assert latest is not None
    assert latest.sequence_number == 2


def test_create_executable_team_share_with_redaction() -> None:
    """测试构建带沙箱热镜像的团队共享包，验证敏感密钥自动脱敏。"""
    engine = DeviceAgnosticSessionRoamingEngine(base_share_domain="https://myrm.corp")

    env_vars = {
        "PROJECT_NAME": "antigravity",
        "MYRM_API_KEY": "sk-secret-99999",
        "DATABASE_PASSWORD": "super-secret-password",
        "APP_ENV": "staging",
        "AUTH_BEARER_TOKEN": "bearer-token-xxxx",
    }

    bundle: ExecutableTeamShareBundle = engine.create_executable_team_share(
        session_id="session_corp_888",
        creator_user_id="user_alice",
        workspace_root="/home/sandbox/project",
        mounted_artifacts=("report.html", "schema.sql"),
        env_variables=env_vars,
        default_role=CollaborationRole.DRIVER,
        expiry_hours=48,
    )

    assert bundle.share_id.startswith("share_")
    assert bundle.share_url.startswith("https://myrm.corp/s/share_")
    assert bundle.default_role == CollaborationRole.DRIVER
    assert bundle.sandbox_mirror.workspace_root == "/home/sandbox/project"
    assert bundle.sandbox_mirror.mounted_artifacts == ("report.html", "schema.sql")

    # 验证脱敏：包含 KEY/PASSWORD/TOKEN 的环境变量必须被剥离
    assert "PROJECT_NAME" in bundle.sandbox_mirror.sanitized_env_keys
    assert "APP_ENV" in bundle.sandbox_mirror.sanitized_env_keys
    assert "MYRM_API_KEY" not in bundle.sandbox_mirror.sanitized_env_keys
    assert "DATABASE_PASSWORD" not in bundle.sandbox_mirror.sanitized_env_keys
    assert "AUTH_BEARER_TOKEN" not in bundle.sandbox_mirror.sanitized_env_keys


def test_fork_and_continue_session_success() -> None:
    """测试受邀团队成员单键分叉并继续执行（Fork & Continue）。"""
    engine = DeviceAgnosticSessionRoamingEngine()

    # 预设父会话断点
    engine.sync_roaming_breakpoint(
        session_id="session_orig_01",
        client_device_id="mac_01",
        platform=DevicePlatform.MAC,
        cursor_message_index=8,
        pending_draft_input="",
        active_background_task_count=0,
        environment_snapshot={},
        sequence_number=1,
    )

    # 创建团队协作共享链接
    bundle = engine.create_executable_team_share(
        session_id="session_orig_01",
        creator_user_id="user_alice",
        workspace_root="/sandboxes/alice_env",
        mounted_artifacts=("plan.md",),
        env_variables={"ROLE": "lead"},
        default_role=CollaborationRole.DRIVER,
    )

    # 团队成员 Bob 接力 Fork
    messages = (
        {"role": "user", "content": "需求评审"},
        {"role": "assistant", "content": "已梳理完毕"},
    )
    result: ForkAndContinueResult = engine.fork_and_continue_session(
        share_id=bundle.share_id,
        operator_user_id="user_bob",
        cloned_messages=messages,
    )

    assert result.forked_session_id.startswith("fork_")
    assert result.parent_session_id == "session_orig_01"
    assert result.operator_user_id == "user_bob"
    assert result.assigned_role == CollaborationRole.DRIVER
    assert result.cloned_message_count == 2
    assert result.resumed_cursor_index == 8
    assert result.new_sandbox_workspace_root.startswith("/sandboxes/fork_")


def test_fork_and_continue_expired_or_invalid_share() -> None:
    """测试不存在或过期的共享凭据在分叉接续时严格抛出异常。"""
    engine = DeviceAgnosticSessionRoamingEngine()

    # 1. 不存在的凭据
    with pytest.raises(KeyError, match="不存在或已过期销毁"):
        engine.fork_and_continue_session(
            share_id="share_invalid_id",
            operator_user_id="user_carol",
            cloned_messages=(),
        )

    # 2. 已过期的凭据
    bundle = engine.create_executable_team_share(
        session_id="session_orig_02",
        creator_user_id="user_alice",
        workspace_root="/root",
        mounted_artifacts=(),
        env_variables={},
        expiry_hours=-1,  # 强制过期
    )

    with pytest.raises(ValueError, match="已于 .* 过期"):
        engine.fork_and_continue_session(
            share_id=bundle.share_id,
            operator_user_id="user_carol",
            cloned_messages=(),
        )
