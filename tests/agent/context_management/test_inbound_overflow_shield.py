"""单元测试：长文本入站防御性分页挂载、大消息防爆 Working Memory 与智能摘要网关套件 (Item 189)。

覆盖测试点：
1. 正常小体量消息直接放行直通 (SAFE_PASS_THROUGH)
2. 超长文本拦截挂载、文件保真落盘与高密骨架摘要 (OVERSIZED_TRUNCATED_AND_MOUNTED)
3. 极端超大载荷保护分类 (EXTREME_PAYLOAD_CLAMPED)
4. 挂载文件切片读取与防路径遍历逃逸安全校验
5. 过期挂载临时文件生命周期清理 (cleanup_stale_mounts)
"""

import os
from pathlib import Path
import tempfile
import time

from myrm_agent_harness.agent.context_management.inbound_shield import (
    InboundMessageOverflowShield,
    InboundMountedDocument,
    InboundPayloadClassification,
    InboundShieldConfig,
    InboundShieldResult,
)


def test_safe_inbound_message_pass_through() -> None:
    """测试常规短消息守门员放行直通。"""
    config = InboundShieldConfig(char_threshold=500, token_threshold=150)
    shield = InboundMessageOverflowShield(config=config)

    normal_message = "你好，请帮我重构一下 user_service.py 中的登录验证逻辑。"
    result = shield.inspect_and_shield(normal_message)

    assert result.is_intercepted is False
    assert result.classification == InboundPayloadClassification.SAFE_PASS_THROUGH
    assert result.shielded_content == normal_message
    assert result.mounted_doc is None
    assert result.saved_tokens == 0
    assert result.read_tool_guidance is None


def test_oversized_inbound_message_interception_and_mounting() -> None:
    """测试超长入站文本防御性挂载、哈希完整性与摘要注入。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        config = InboundShieldConfig(
            char_threshold=1000,
            token_threshold=300,
            max_skeleton_summary_chars=200,
            mount_directory_relative=".context/inbound",
        )
        shield = InboundMessageOverflowShield(config=config)

        # 构造包含标题和错误堆栈的万字长文本
        paragraphs = [
            "# System Production Crash Log Analysis",
            "This document describes the severe crash occurred at 03:00 UTC.",
        ]
        for i in range(1, 100):
            paragraphs.append(
                f"Line {i}: [ERROR] NullPointerException at com.example.service.Worker.process(Worker.java:{i * 10})"
            )
        paragraphs.append("Final statement: please analyze root cause and provide patch.")
        huge_payload = "\n".join(paragraphs)
        assert len(huge_payload) > 5000

        result = shield.inspect_and_shield(
            message_content=huge_payload,
            message_id="msg_crash_report_101",
            workspace_root=workspace,
        )

        assert result.is_intercepted is True
        assert (
            result.classification
            == InboundPayloadClassification.OVERSIZED_TRUNCATED_AND_MOUNTED
        )
        assert result.mounted_doc is not None
        assert result.mounted_doc.mount_id == "msg_crash_report_101"
        assert result.saved_tokens > 500
        assert "read_file" in (result.read_tool_guidance or "")

        # 检查物理落盘文件保真度
        mounted_path = workspace / result.mounted_doc.relative_path
        assert mounted_path.exists()
        saved_text = mounted_path.read_text(encoding="utf-8")
        assert saved_text == huge_payload
        assert len(saved_text) == result.mounted_doc.char_count

        # 检查骨架摘要与特征提取
        assert len(result.mounted_doc.skeleton_summary) <= 200
        assert "error_trace" in result.mounted_doc.key_entities
        assert "markdown_outline" in result.mounted_doc.key_entities
        assert "[INBOUND_OVERFLOW_SHIELD" in result.shielded_content


def test_extreme_payload_clamping_classification() -> None:
    """测试极端超大文本阈值分类。"""
    config = InboundShieldConfig(
        char_threshold=500,
        token_threshold=100,
        extreme_char_threshold=5000,
    )
    shield = InboundMessageOverflowShield(config=config)

    extreme_payload = "A" * 6000
    result = shield.inspect_and_shield(extreme_payload)

    assert result.is_intercepted is True
    assert (
        result.classification == InboundPayloadClassification.EXTREME_PAYLOAD_CLAMPED
    )
    assert result.mounted_doc is not None
    assert result.mounted_doc.char_count == 6000


def test_read_mounted_payload_slice_and_path_traversal_defense() -> None:
    """测试挂载大文本按行切片读取与防路径穿越逃逸。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        config = InboundShieldConfig(char_threshold=200, token_threshold=50)
        shield = InboundMessageOverflowShield(config=config)

        sample_lines = [f"Record item #{idx}" for idx in range(1, 21)]
        payload = "\n".join(sample_lines)

        result = shield.inspect_and_shield(
            message_content=payload,
            message_id="slice_test",
            workspace_root=workspace,
        )
        assert result.mounted_doc is not None

        # 1. 切片读取第 5 行到第 8 行
        slice_content = shield.read_mounted_payload(
            relative_path=result.mounted_doc.relative_path,
            workspace_root=workspace,
            start_line=5,
            end_line=8,
        )
        expected_slice = "\n".join(sample_lines[4:8])
        assert slice_content == expected_slice

        # 2. 全量读取
        full_content = shield.read_mounted_payload(
            relative_path=result.mounted_doc.relative_path,
            workspace_root=workspace,
        )
        assert full_content == payload

        # 3. 越界切片防御
        empty_slice = shield.read_mounted_payload(
            relative_path=result.mounted_doc.relative_path,
            workspace_root=workspace,
            start_line=100,
            end_line=150,
        )
        assert empty_slice == ""

        # 4. 路径穿越逃逸防御
        try:
            shield.read_mounted_payload(
                relative_path="../outside_secret.txt",
                workspace_root=workspace,
            )
            raise AssertionError("Should have raised PermissionError")
        except PermissionError:
            pass


def test_cleanup_stale_mounts() -> None:
    """测试过期挂载文件的生命周期清理逻辑。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        config = InboundShieldConfig(char_threshold=100, token_threshold=20)
        shield = InboundMessageOverflowShield(config=config)

        # 挂载两个大文本
        res1 = shield.inspect_and_shield("Data A " * 100, "doc_a", workspace)
        res2 = shield.inspect_and_shield("Data B " * 100, "doc_b", workspace)

        assert res1.mounted_doc is not None
        assert res2.mounted_doc is not None

        doc_a_path = workspace / res1.mounted_doc.relative_path
        doc_b_path = workspace / res2.mounted_doc.relative_path

        # 模拟 doc_a 在 2 天前创建
        stale_time = time.time() - 172800
        os.utime(doc_a_path, (stale_time, stale_time))

        # 执行保留 1 天 (86400秒) 的清理
        deleted_count = shield.cleanup_stale_mounts(
            workspace_root=workspace, retention_seconds=86400
        )

        assert deleted_count == 1
        assert not doc_a_path.exists()
        assert doc_b_path.exists()
