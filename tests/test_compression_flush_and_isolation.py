# [POS] tests/test_compression_flush_and_isolation.py
# [INPUT] PreCompressionMemoryFlushHook, SubagentMemoryIsolationController, StatelessCronContextGuard from myrm_agent_harness.agent.context_management.compression_flush
# [OUTPUT] test_pre_compression_memory_flush_empty_and_success, test_pre_compression_memory_flush_handler_failure, test_subagent_memory_isolation_overlay_lifecycle, test_subagent_selective_merge_and_auto_purge, test_stateless_cron_guard_sanitization

"""Unit test suite for compression flush protocol, subagent memory isolation, and stateless cron guard."""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.compression_flush import (
    EphemeralMemoryOverlaySpec,
    FlushItem,
    FlushTriggerReason,
    MemoryIsolationScope,
    PreCompressionMemoryFlushHook,
    StatelessCronContextGuard,
    StatelessCronSpec,
    SubagentMemoryIsolationController,
    SubagentMemoryPolicy,
)


def test_pre_compression_memory_flush_empty_and_success() -> None:
    """Verify flush executes cleanly on empty buffer and successfully commits pending items."""
    hook = PreCompressionMemoryFlushHook()
    session_id = "test-session-001"

    # 1. Empty buffer flush
    result_empty = hook.execute_pre_compression_flush(
        session_id, FlushTriggerReason.COMPRESSION
    )
    assert result_empty.is_success is True
    assert result_empty.flushed_items_count == 0
    assert result_empty.flushed_categories == []

    # 2. Register pending items
    item1 = FlushItem(
        item_id="pref-1",
        category="user_preference",
        content="偏好使用单行精简日志",
    )
    item2 = FlushItem(
        item_id="const-1",
        category="architectural_constraint",
        content="严禁引入重量级守护进程",
    )
    hook.register_pending_item(session_id, item1)
    hook.register_pending_items(session_id, [item2])

    assert hook.get_pending_count(session_id) == 2
    assert len(hook.get_pending_items(session_id)) == 2

    # 3. Execute flush without custom handler (default memory archive fallback)
    result_flush = hook.execute_pre_compression_flush(
        session_id, FlushTriggerReason.COMPRESSION
    )
    assert result_flush.is_success is True
    assert result_flush.flushed_items_count == 2
    assert "user_preference" in result_flush.flushed_categories
    assert "architectural_constraint" in result_flush.flushed_categories

    # Buffer should now be cleared and moved to flushed archive
    assert hook.get_pending_count(session_id) == 0
    archived = hook.get_flushed_archive(session_id)
    assert len(archived) == 2
    assert archived[0].item_id == "pref-1"


def test_pre_compression_memory_flush_handler_failure() -> None:
    """Verify pending buffer is not purged if the external persistence handler fails."""
    hook = PreCompressionMemoryFlushHook()
    session_id = "test-session-err"

    item = FlushItem(
        item_id="fact-1",
        category="factual",
        content="重要配置项已更改为 SQLite WAL",
    )
    hook.register_pending_item(session_id, item)

    def failing_handler(sess: str, items: list[FlushItem]) -> bool:
        raise OSError("Disk I/O timeout")

    hook.register_persistence_handler(failing_handler)

    result = hook.execute_pre_compression_flush(session_id)
    assert result.is_success is False
    assert "Disk I/O timeout" in result.error_message

    # Pending items must still remain intact to prevent data loss!
    assert hook.get_pending_count(session_id) == 1
    assert hook.get_pending_items(session_id)[0].item_id == "fact-1"


def test_subagent_memory_isolation_overlay_lifecycle() -> None:
    """Verify subagent memory isolation supports parent read-only views and ephemeral overlays."""
    controller = SubagentMemoryIsolationController()
    parent_items = [
        FlushItem(
            item_id="root-rule",
            category="rule",
            content="全局单一职责",
        ),
        FlushItem(
            item_id="var-target",
            category="variable",
            content="父级初始值 A",
        ),
    ]

    spec = EphemeralMemoryOverlaySpec(
        overlay_id="sub-task-42",
        parent_session_id="parent-session-1",
        max_overlay_items=10,
    )
    policy = SubagentMemoryPolicy(
        isolation_scope=MemoryIsolationScope.SUBAGENT_OVERLAY,
        allow_profile_read=True,
        allow_ephemeral_write=True,
    )

    controller.create_subagent_overlay(spec, parent_items=parent_items, policy=policy)
    assert controller.has_overlay("sub-task-42") is True

    # Initial view has parent items
    initial_view = controller.get_subagent_view("sub-task-42")
    assert len(initial_view) == 2

    # Subagent writes ephemeral item
    new_sub_item = FlushItem(
        item_id="temp-sub-1",
        category="subagent_scratch",
        content="中间探针探测结果: 端口 8080 正常",
    )
    # Subagent overrides a parent variable item
    override_sub_item = FlushItem(
        item_id="var-target",
        category="variable",
        content="子级覆盖值 B",
    )
    assert controller.append_subagent_ephemeral("sub-task-42", new_sub_item) is True
    assert controller.append_subagent_ephemeral("sub-task-42", override_sub_item) is True

    # View should contain 3 items, with "var-target" overridden by subagent
    active_view = controller.get_subagent_view("sub-task-42")
    assert len(active_view) == 3
    var_item = next(it for it in active_view if it.item_id == "var-target")
    assert var_item.content == "子级覆盖值 B"

    # Only ephemeral items
    ephemerals = controller.get_overlay_ephemeral_items("sub-task-42")
    assert len(ephemerals) == 2


def test_subagent_selective_merge_and_auto_purge() -> None:
    """Verify selective merging harvests chosen ephemeral items and auto-purges the overlay."""
    controller = SubagentMemoryIsolationController()
    spec = EphemeralMemoryOverlaySpec(
        overlay_id="sub-task-merge",
        parent_session_id="parent-session-2",
        allow_selective_merge=True,
        auto_purge_on_finish=True,
    )
    controller.create_subagent_overlay(spec)

    item_noise = FlushItem(
        item_id="noise-1",
        category="scratch",
        content="试错步骤 1 (已废弃)",
    )
    item_valuable = FlushItem(
        item_id="insight-final",
        category="architectural_decision",
        content="结论: 采用内存映射临时文件代替管道",
    )
    controller.append_subagent_ephemeral("sub-task-merge", item_noise)
    controller.append_subagent_ephemeral("sub-task-merge", item_valuable)

    # Selective harvest only the valuable item
    harvested = controller.merge_selective_to_parent(
        "sub-task-merge", ["insight-final"]
    )
    assert len(harvested) == 1
    assert harvested[0].item_id == "insight-final"
    assert harvested[0].content == "结论: 采用内存映射临时文件代替管道"

    # Overlay should be purged after finish
    assert controller.has_overlay("sub-task-merge") is False
    assert controller.get_subagent_view("sub-task-merge") == []


def test_stateless_cron_guard_sanitization() -> None:
    """Verify stateless cron guard strips profile injections and checks self-containment."""
    spec = StatelessCronSpec(
        task_id="cron-cleanup-01",
        task_name="夜间日志自动轮转",
        strip_user_profile=True,
        require_self_contained=True,
    )

    contaminated_prompt = (
        "<!-- [USER PROFILE] 用户喜欢 Rust，要求严格类型 -->\n\n"
        "<!-- [USER DIALECTIC MIND] 即时心智状态与瞬间关切\n焦点: 优化 SQLite 锁 -->\n\n"
        "执行夜间日志轮转清理，归档 7 天前的历史 trace 文件。"
    )

    cleaned_prompt, was_modified = StatelessCronContextGuard.sanitize_cron_prompt(
        contaminated_prompt, spec
    )
    assert was_modified is True
    assert "<!-- [USER PROFILE]" not in cleaned_prompt
    assert "<!-- [USER DIALECTIC MIND]" not in cleaned_prompt
    assert "执行夜间日志轮转清理，归档 7 天前的历史 trace 文件。" in cleaned_prompt

    # Validate self containment
    assert StatelessCronContextGuard.validate_self_contained(cleaned_prompt) is True
    assert StatelessCronContextGuard.validate_self_contained("  ") is False
