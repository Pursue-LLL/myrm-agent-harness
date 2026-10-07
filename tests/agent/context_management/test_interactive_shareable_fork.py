"""单元测试：具备交互式运行时状态的会话免密分享链接、多端只读/协作穿透与一键无损分叉套件 (Item 193)。

覆盖测试点：
1. 密码学时效签名凭据生成与高保真透视视口解析
2. 恶意篡改攻击防御与伪造签名硬拦截 (PermissionError)
3. 凭据时效过期拦截防御 (TimeoutError)
4. 只读权限透视视口硬拦截无损分叉 (PermissionError)
5. 一键无损分叉接力克隆、血缘追溯与工件无损迁移
"""

import pytest

from myrm_agent_harness.agent.context_management.shareable_fork import (
    InteractiveShareableForkEngine,
    LosslessForkResult,
    ShareAccessPermission,
    ShareTokenPayload,
    ShareableForkConfig,
    SharedSessionPerspective,
)


def test_generate_share_token_and_resolve_perspective() -> None:
    """测试生成带 HMAC-SHA256 签名的凭据与解析高保真只读透视视口。"""
    engine = InteractiveShareableForkEngine()
    session_id = "sess_arch_review_2026"
    issuer = "alice_lead"

    # 生成允许无损分叉的分享凭证
    token = engine.generate_share_token(
        session_id=session_id,
        issuer_id=issuer,
        permission=ShareAccessPermission.ALLOW_INTERACTIVE_FORK,
        include_artifacts=True,
        ttl_seconds=3600,
    )

    assert token.session_id == session_id
    assert token.issuer_id == issuer
    assert token.permission == ShareAccessPermission.ALLOW_INTERACTIVE_FORK
    assert len(token.signature_hmac) == 64

    # 协作人解析透视视口
    messages = (
        ("user", "请帮我评估并设计上下文防爆网关。"),
        ("assistant", "这是基于分级守门员和沙箱挂载的最优架构方案。"),
    )
    artifacts = (
        ("gateway_spec.md", "file:///workspace/docs/spec.md"),
    )

    perspective = engine.verify_and_resolve_share(
        share_token=token,
        session_title="上下文防爆网关架构评审",
        messages=messages,
        artifacts=artifacts,
    )

    assert perspective.session_id == session_id
    assert perspective.session_title == "上下文防爆网关架构评审"
    assert len(perspective.messages_snapshot) == 2
    assert len(perspective.artifacts_snapshot) == 1
    assert perspective.can_fork is True
    assert "2 turns" in perspective.execution_trace_summary


def test_tampered_signature_defense() -> None:
    """测试恶意篡改载荷或伪造签名时触发的硬拦截防御。"""
    engine = InteractiveShareableForkEngine()
    token = engine.generate_share_token(
        session_id="sess_normal",
        issuer_id="bob",
        permission=ShareAccessPermission.ALLOW_INTERACTIVE_FORK,
    )

    # 1. 篡改会话 ID (试图越权访问其他会话)
    tampered_token = ShareTokenPayload(
        share_id=token.share_id,
        session_id="sess_admin_secret",
        issuer_id=token.issuer_id,
        permission=token.permission,
        include_artifacts=token.include_artifacts,
        expires_at_iso=token.expires_at_iso,
        signature_hmac=token.signature_hmac,
    )

    with pytest.raises(PermissionError, match="Invalid share token cryptographic signature"):
        engine.verify_and_resolve_share(
            share_token=tampered_token,
            session_title="篡改测试",
            messages=(),
        )

    # 2. 伪造错误 HMAC 签名
    fake_sig_token = ShareTokenPayload(
        share_id=token.share_id,
        session_id=token.session_id,
        issuer_id=token.issuer_id,
        permission=token.permission,
        include_artifacts=token.include_artifacts,
        expires_at_iso=token.expires_at_iso,
        signature_hmac="a" * 64,
    )

    with pytest.raises(PermissionError, match="Invalid share token cryptographic signature"):
        engine.verify_and_resolve_share(
            share_token=fake_sig_token,
            session_title="伪造签名测试",
            messages=(),
        )


def test_expired_share_token_defense() -> None:
    """测试时效过期凭据的主动防御拦截。"""
    engine = InteractiveShareableForkEngine()
    # 生成已过期的 token (ttl = -10 秒)
    token = engine.generate_share_token(
        session_id="sess_expired",
        issuer_id="carol",
        ttl_seconds=-10,
    )

    with pytest.raises(TimeoutError, match="has expired"):
        engine.verify_and_resolve_share(
            share_token=token,
            session_title="过期会话",
            messages=(),
        )


def test_read_only_permission_blocks_fork() -> None:
    """测试只读权限透视视口硬拦截无损分叉。"""
    engine = InteractiveShareableForkEngine()
    token = engine.generate_share_token(
        session_id="sess_readonly",
        issuer_id="dave",
        permission=ShareAccessPermission.READ_ONLY_VIEW,
    )

    perspective = engine.verify_and_resolve_share(
        share_token=token,
        session_title="公司制度宣讲（只读）",
        messages=(("user", "请总结考勤规范"),),
    )

    assert perspective.can_fork is False

    with pytest.raises(PermissionError, match="does not permit lossless forking"):
        engine.execute_lossless_fork(
            perspective=perspective,
            target_user_id="collaborator_eve",
        )


def test_execute_lossless_fork_success() -> None:
    """测试一键无损分叉接力克隆与血缘追溯。"""
    engine = InteractiveShareableForkEngine()
    token = engine.generate_share_token(
        session_id="sess_seed_story",
        issuer_id="frank_director",
        permission=ShareAccessPermission.ALLOW_INTERACTIVE_FORK,
    )

    messages = (
        ("user", "请根据世界观构思第 1 章故事。"),
        ("assistant", "第 1 章：初抵新星，雷暴与旧遗迹。"),
    )
    artifacts = (
        ("chapter1_draft.docx", "file:///workspace/chapters/c1.docx"),
        ("world_bible.json", "file:///workspace/meta/bible.json"),
    )

    perspective = engine.verify_and_resolve_share(
        share_token=token,
        session_title="科幻长篇创作工程",
        messages=messages,
        artifacts=artifacts,
    )

    # 协作人一键 Fork 接力推进
    fork_result = engine.execute_lossless_fork(
        perspective=perspective,
        target_user_id="grace_writer",
        forked_session_id="fork_branch_c1_revision",
    )

    assert fork_result.forked_session_id == "fork_branch_c1_revision"
    assert fork_result.original_session_id == "sess_seed_story"
    assert fork_result.forked_by_user_id == "grace_writer"
    assert fork_result.copied_message_count == 2
    assert fork_result.copied_artifact_count == 2
    assert fork_result.new_session_uri == "session://fork_branch_c1_revision"

    # 查询血缘记录
    record = engine.get_fork_record("fork_branch_c1_revision")
    assert record is not None
    assert record.original_session_id == "sess_seed_story"
