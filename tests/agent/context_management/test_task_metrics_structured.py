"""Tests for structured compression metrics."""

from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    ArchiveRestoreBudgetPolicy,
    TaskMetrics,
    clear_task_metrics,
    create_task_metrics,
    evaluate_archive_refetch_for_path,
    get_all_active_metrics,
    get_or_create_task_metrics,
    get_task_metrics,
    record_archive_refetch_for_path,
)


def test_record_compression_stores_structured_fields() -> None:
    metrics = TaskMetrics(task_id="chat_123")

    metrics.record_compression(
        tokens_saved=1200,
        compression_type="compress",
        details="Compressed 2 tool call groups",
        group_count=2,
        dedup_tokens_saved=300,
        integrity_skipped=1,
    )

    event = metrics.compression_events[0]
    assert event.group_count == 2
    assert event.dedup_tokens_saved == 300
    assert event.integrity_skipped == 1


def test_task_metrics_to_dict_exports_compression_events() -> None:
    metrics = TaskMetrics(task_id="chat_123")
    metrics.record_compression(
        tokens_saved=900,
        compression_type="compress",
        details="Compressed 1 tool call group",
        group_count=1,
        dedup_tokens_saved=100,
        integrity_skipped=0,
        offload_failure_kinds={"quota_exceeded": 2},
        archive_written_count=1,
        archive_reused_count=2,
        archive_bytes_written=1024,
        archive_bytes_reused=2048,
    )

    exported = metrics.to_dict()
    events = exported["compression_events"]

    assert isinstance(events, list)
    assert len(events) == 1
    assert events[0]["group_count"] == 1
    assert events[0]["dedup_tokens_saved"] == 100
    assert events[0]["integrity_skipped"] == 0
    assert events[0]["offload_failure_kinds"] == {"quota_exceeded": 2}
    assert events[0]["archive_written_count"] == 1
    assert events[0]["archive_reused_count"] == 2
    assert events[0]["archive_bytes_written"] == 1024
    assert events[0]["archive_bytes_reused"] == 2048
    assert exported["offload_failure_kinds"] == {"quota_exceeded": 2}
    assert exported["archive_written_count"] == 1
    assert exported["archive_reused_count"] == 2
    assert exported["archive_bytes_written"] == 1024
    assert exported["archive_bytes_reused"] == 2048


def test_add_input_and_output_tokens() -> None:
    metrics = TaskMetrics(task_id="chat_tok")
    metrics.add_input_tokens(500)
    metrics.add_input_tokens(300)
    metrics.add_output_tokens(100)
    assert metrics.total_input_tokens == 800
    assert metrics.total_output_tokens == 100
    assert metrics.tokens_per_task == 900


def test_record_refetch() -> None:
    metrics = TaskMetrics(task_id="chat_refetch")
    metrics.record_refetch(
        reason="file_path_lost",
        tool_name="read_file",
        estimated_tokens=200,
        archive_path=".context/chat_refetch/compacted/tool.txt",
    )
    assert metrics.refetch_count == 1
    assert metrics.refetch_events[0].reason == "file_path_lost"
    assert metrics.refetch_events[0].tool_name == "read_file"
    assert metrics.refetch_events[0].estimated_tokens == 200
    assert metrics.refetch_events[0].archive_path.endswith("tool.txt")


def test_record_archive_refetch_for_context_path() -> None:
    chat_id = "chat_archive_refetch"
    try:
        create_task_metrics(chat_id)
        recorded = record_archive_refetch_for_path(
            f".context/{chat_id}/compacted/search_result.txt",
            estimated_tokens=450,
        )
        metrics = get_task_metrics(chat_id)
        assert recorded is True
        assert metrics is not None
        assert metrics.archive_refetch_count == 1
        assert metrics.archive_refetch_tokens == 450
        assert metrics.archive_restore_requested_count == 1
        assert metrics.archive_restore_allowed_count == 1
        assert metrics.pruning_net_tokens_saved == -450
        assert metrics.net_tokens_saved == -450
    finally:
        clear_task_metrics(chat_id)


def test_restore_blocked_count_uses_outcome_events_as_source_of_truth() -> None:
    metrics = TaskMetrics(task_id="chat_restore_outcome_source")

    metrics.record_archive_restore_blocked(
        reason="archive_restore_range_required",
        archive_path=".context/chat_restore_outcome_source/compacted/tool.txt",
        estimated_tokens=2500,
    )

    assert metrics.archive_restore_blocked_count == 0
    assert len(metrics.archive_restore_block_events) == 1

    metrics.record_archive_restore_outcome(
        outcome="blocked",
        reason="archive_restore_range_required",
        archive_path=".context/chat_restore_outcome_source/compacted/tool.txt",
        estimated_tokens=2500,
    )

    assert metrics.archive_restore_requested_count == 1
    assert metrics.archive_restore_blocked_count == 1
    assert metrics.archive_restore_blocked_ratio == 1.0


def test_record_archive_refetch_ignores_non_context_path() -> None:
    assert record_archive_refetch_for_path("workspace/file.txt", estimated_tokens=50) is False


def test_archive_refetch_blocks_session_mismatch() -> None:
    try:
        create_task_metrics("chat_b")
        decision = evaluate_archive_refetch_for_path(
            ".context/chat_a/compacted/tool.txt",
            estimated_tokens=50,
            current_chat_id="chat_b",
        )

        assert decision.is_archive_path is True
        assert decision.allowed is False
        assert decision.reason == "archive_refetch_session_mismatch"
        assert decision.guidance.severity == "critical"
        assert decision.guidance.primary_restore_arg == ""
        metrics = get_task_metrics("chat_b")
        assert metrics is not None
        assert metrics.archive_restore_requested_count == 1
        assert metrics.archive_restore_blocked_count == 1
    finally:
        clear_task_metrics("chat_b")


def test_archive_refetch_blocks_repeated_path_reads() -> None:
    chat_id = "chat_archive_budget"
    path = f".context/{chat_id}/compacted/search_result.txt"
    try:
        create_task_metrics(chat_id)
        assert evaluate_archive_refetch_for_path(path, estimated_tokens=100).recorded is True
        assert evaluate_archive_refetch_for_path(path, estimated_tokens=100).recorded is True

        decision = evaluate_archive_refetch_for_path(path, estimated_tokens=100)

        assert decision.allowed is False
        assert decision.reason == "archive_refetch_path_budget_exceeded"
        metrics = get_task_metrics(chat_id)
        assert metrics is not None
        assert metrics.archive_restore_blocked_count == 1
        assert metrics.archive_restore_requested_count == 3
        assert metrics.archive_restore_allowed_count == 2
        assert round(metrics.archive_restore_blocked_ratio, 4) == 0.3333
        assert metrics.archive_restore_block_events[0].reason == "archive_refetch_path_budget_exceeded"
        event = metrics.archive_restore_block_events[0].to_dict()
        assert event["reason_label_key"] == "archive_refetch_path_budget_exceeded"
        assert event["primary_restore_arg"] == f"{path}:1-200"
        assert event["recommended_ranges"] == [
            f"{path}:1-200",
            f"{path}:201-400",
            f"{path}:401-600",
        ]
        assert event["restore_range_hints"][0] == {
            "range_arg": f"{path}:1-200",
            "reason": "fallback_chunk",
            "start_line": 1,
            "end_line": 200,
            "line": 1,
        }
    finally:
        clear_task_metrics(chat_id)


def test_archive_refetch_blocks_token_budget() -> None:
    chat_id = "chat_archive_token_budget"
    path = f".context/{chat_id}/compacted/search_result.txt"
    try:
        create_task_metrics(chat_id)
        decision = evaluate_archive_refetch_for_path(
            path,
            estimated_tokens=20_000,
            is_range_read=True,
        )

        assert decision.allowed is False
        assert decision.reason == "archive_refetch_token_budget_exceeded"
        metrics = get_task_metrics(chat_id)
        assert metrics is not None
        assert metrics.archive_restore_blocked_count == 1
        assert metrics.archive_restore_requested_count == 1
        assert metrics.archive_restore_allowed_count == 0
        assert metrics.archive_restore_block_events[0].message
        assert metrics.archive_restore_block_events[0].suggested_action
        assert metrics.archive_restore_block_events[0].guidance.primary_restore_arg == f"{path}:1-200"
    finally:
        clear_task_metrics(chat_id)


def test_archive_refetch_requires_range_for_large_full_restore() -> None:
    chat_id = "chat_archive_full_restore_budget"
    path = f".context/{chat_id}/compacted/search_result.txt"
    try:
        create_task_metrics(chat_id)
        decision = evaluate_archive_refetch_for_path(path, estimated_tokens=2_500)

        assert decision.allowed is False
        assert decision.reason == "archive_restore_range_required"
        metrics = get_task_metrics(chat_id)
        assert metrics is not None
        assert metrics.archive_restore_blocked_count == 1
        assert metrics.archive_restore_requested_count == 1
        assert metrics.archive_restore_allowed_count == 0
        event = metrics.archive_restore_block_events[0].to_dict()
        assert event["reason"] == "archive_restore_range_required"
        assert "chunk_restore_args" in event["suggested_action"]
        assert "guidance" not in event
        assert event["reason_label_key"] == "archive_restore_range_required"
        assert event["severity"] == "warning"
        assert event["primary_restore_arg"] == f"{path}:1-200"
        assert event["recommended_ranges"] == [
            f"{path}:1-200",
            f"{path}:201-400",
            f"{path}:401-600",
        ]
        assert event["restore_range_hints"][0]["reason"] == "fallback_chunk"
    finally:
        clear_task_metrics(chat_id)


def test_archive_refetch_uses_injected_restore_budget_policy() -> None:
    chat_id = "chat_archive_custom_budget"
    path = f".context/{chat_id}/compacted/search_result.txt"
    try:
        create_task_metrics(chat_id)
        decision = evaluate_archive_refetch_for_path(
            path,
            estimated_tokens=150,
            policy=ArchiveRestoreBudgetPolicy(
                max_refetches_per_path=1,
                max_refetch_tokens=100,
            ),
        )

        assert decision.allowed is False
        assert decision.reason == "archive_refetch_token_budget_exceeded"
        assert "restore token budget" in decision.message
    finally:
        clear_task_metrics(chat_id)


def test_archive_refetch_can_evaluate_allowed_read_without_recording() -> None:
    chat_id = "chat_archive_preflight"
    path = f".context/{chat_id}/compacted/search_result.txt"
    try:
        create_task_metrics(chat_id)
        decision = evaluate_archive_refetch_for_path(
            path,
            estimated_tokens=100,
            record_allowed=False,
        )

        metrics = get_task_metrics(chat_id)
        assert decision.allowed is True
        assert decision.recorded is False
        assert metrics is not None
        assert metrics.archive_refetch_count == 0
        assert metrics.archive_restore_requested_count == 1
        assert metrics.archive_restore_allowed_count == 1
    finally:
        clear_task_metrics(chat_id)


def test_pruning_net_tokens_saved_subtracts_archive_restore_costs() -> None:
    metrics = TaskMetrics(task_id="chat_pruning_net")
    metrics.record_compression(
        tokens_saved=1200,
        compression_type="cache_ttl_prune",
        archive_count=1,
        original_tokens=4000,
    )
    metrics.record_refetch(
        reason="archive_reference_read",
        tool_name="file_read_tool",
        estimated_tokens=300,
        archive_path=".context/chat_pruning_net/compacted/tool.txt",
    )
    metrics.record_archive_restore_result(
        archive_path=".context/chat_pruning_net/compacted/tool.txt",
        restore_arg=".context/chat_pruning_net/compacted/tool.txt:1-20",
        start_line=1,
        end_line=20,
        restored_line_count=20,
        estimated_tokens=200,
        restored_bytes=2048,
    )

    exported = metrics.to_dict()
    assert exported["pruning_tokens_saved"] == 1200
    assert exported["archive_refetch_tokens"] == 300
    assert exported["archive_restore_result_tokens"] == 200
    assert exported["archive_restore_requested_count"] == 0
    assert exported["archive_restore_allowed_count"] == 0
    assert exported["archive_restore_blocked_count"] == 0
    assert exported["archive_restore_blocked_ratio"] == 0.0
    assert exported["pruning_net_tokens_saved"] == 700
    assert exported["net_tokens_saved"] == 700
    assert exported["pruning_restore_cost_ratio"] == 200 / 1200
    assert exported["pruning_restore_roi_ratio"] == 700 / 1200
    assert exported["archive_deferred_count"] == 0
    assert exported["archive_deferred_reasons"] == {}
    assert exported["pruning_backoff_applied"] is False
    assert exported["pruning_backoff_reasons"] == {}
    assert exported["pruning_effective_soft_trim_ratio"] == 0.0
    assert exported["pruning_effective_hard_clear_ratio"] == 0.0
    assert exported["pruning_effective_min_prunable_tokens"] == 0
    assert exported["pruning_backoff_sample_count"] == 0
    assert exported["pruning_backoff_bad_signal_count"] == 0
    assert exported["pruning_backoff_recovery_sample_count"] == 0
    assert exported["archive_restore_budget"] == {
        "max_refetches_per_path": 2,
        "max_refetch_tokens": 16_000,
        "max_full_restore_tokens": 2_000,
    }


def test_cache_ttl_pruning_backoff_metrics_are_exported() -> None:
    metrics = TaskMetrics(task_id="chat_pruning_backoff")
    metrics.record_compression(
        tokens_saved=800,
        compression_type="cache_ttl_prune",
        archive_count=1,
        backoff_applied=True,
        backoff_reasons=["high_restore_cost_ratio", "low_restore_roi_ratio"],
        effective_soft_trim_ratio=0.4,
        effective_hard_clear_ratio=0.6,
        effective_min_prunable_tokens=25_000,
        backoff_sample_count=4,
        backoff_bad_signal_count=2,
        backoff_recovery_sample_count=0,
    )

    exported = metrics.to_dict()

    assert exported["pruning_backoff_applied"] is True
    assert exported["pruning_backoff_reasons"] == {
        "high_restore_cost_ratio": 1,
        "low_restore_roi_ratio": 1,
    }
    assert exported["pruning_effective_soft_trim_ratio"] == 0.4
    assert exported["pruning_effective_hard_clear_ratio"] == 0.6
    assert exported["pruning_effective_min_prunable_tokens"] == 25_000
    assert exported["pruning_backoff_sample_count"] == 4
    assert exported["pruning_backoff_bad_signal_count"] == 2
    assert exported["pruning_backoff_recovery_sample_count"] == 0
    assert exported["compression_events"][0]["backoff_reasons"] == [
        "high_restore_cost_ratio",
        "low_restore_roi_ratio",
    ]


def test_archive_deferred_metrics_are_separate_from_unmodified_deferred() -> None:
    metrics = TaskMetrics(task_id="chat_archive_deferred")
    metrics.record_compression(
        tokens_saved=500,
        compression_type="cache_ttl_prune",
        soft_trimmed_count=1,
        archive_deferred_count=1,
        archive_deferred_reasons={"archive_count_budget": 1},
        archive_deferred_soft_trimmed_count=1,
        archive_deferred_soft_trimmed_reasons={"archive_count_budget": 1},
    )

    exported = metrics.to_dict()

    assert exported["prune_deferred_count"] == 0
    assert exported["archive_deferred_count"] == 1
    assert exported["archive_deferred_soft_trimmed_count"] == 1


def test_get_or_create_none_returns_none() -> None:
    result = get_or_create_task_metrics(None)
    assert result is None


def test_get_or_create_with_id() -> None:
    chat_id = "chat_get_or_create_test"
    try:
        result = get_or_create_task_metrics(chat_id)
        assert result is not None
        assert result.task_id == chat_id
    finally:
        clear_task_metrics(chat_id)


def test_get_all_active_metrics() -> None:
    chat_id = "chat_active_metrics_test"
    try:
        create_task_metrics(chat_id)
        all_metrics = get_all_active_metrics()
        assert chat_id in all_metrics
    finally:
        clear_task_metrics(chat_id)


def test_clear_nonexistent_is_safe() -> None:
    clear_task_metrics("nonexistent_chat_id_12345")


def test_compression_ineffective_streak_field() -> None:
    metrics = TaskMetrics(task_id="chat_streak")
    assert metrics.compression_ineffective_streak == 0
    metrics.compression_ineffective_streak = 3
    assert metrics.compression_ineffective_streak == 3


def test_to_summary_format() -> None:
    metrics = TaskMetrics(task_id="chat_summary_test")
    metrics.add_input_tokens(1000)
    summary = metrics.to_summary()
    assert "chat_sum" in summary
    assert "tokens_per_task" in summary


def test_get_task_metrics_existing() -> None:
    chat_id = "chat_get_metrics_existing"
    try:
        create_task_metrics(chat_id)
        result = get_task_metrics(chat_id)
        assert result is not None
        assert result.task_id == chat_id
    finally:
        clear_task_metrics(chat_id)


def test_get_task_metrics_nonexistent() -> None:
    result = get_task_metrics("nonexistent_get_metrics_777")
    assert result is None


def test_cleanup_expired_metrics() -> None:
    """Trigger _cleanup_expired_metrics_unsafe via get_or_create when store is full."""
    from datetime import timedelta

    from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
        MAX_METRICS_ENTRIES,
        _store_lock,
        _task_metrics_store,
    )

    original_items = {}
    with _store_lock:
        original_items = dict(_task_metrics_store)

    injected_ids = []
    try:
        with _store_lock:
            for i in range(MAX_METRICS_ENTRIES):
                cid = f"__cleanup_test_{i}"
                m = TaskMetrics(task_id=cid)
                m.task_start_time = m.task_start_time - timedelta(days=2)
                _task_metrics_store[cid] = m
                injected_ids.append(cid)

        result = get_or_create_task_metrics("__cleanup_trigger")
        assert result is not None

        with _store_lock:
            remaining_injected = sum(1 for cid in injected_ids if cid in _task_metrics_store)
        assert remaining_injected < MAX_METRICS_ENTRIES
    finally:
        with _store_lock:
            for cid in injected_ids:
                _task_metrics_store.pop(cid, None)
            _task_metrics_store.pop("__cleanup_trigger", None)
            _task_metrics_store.update(original_items)


def test_cleanup_over_limit_removes_oldest() -> None:
    """When TTL-based cleanup isn't enough, oldest entries are removed."""
    from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
        MAX_METRICS_ENTRIES,
        _store_lock,
        _task_metrics_store,
    )

    original_items = {}
    with _store_lock:
        original_items = dict(_task_metrics_store)

    injected_ids = []
    try:
        with _store_lock:
            _task_metrics_store.clear()
            for i in range(MAX_METRICS_ENTRIES):
                cid = f"__fresh_test_{i}"
                _task_metrics_store[cid] = TaskMetrics(task_id=cid)
                injected_ids.append(cid)

        result = get_or_create_task_metrics("__fresh_trigger")
        assert result is not None

        with _store_lock:
            assert len(_task_metrics_store) <= MAX_METRICS_ENTRIES
    finally:
        with _store_lock:
            _task_metrics_store.clear()
            _task_metrics_store.update(original_items)
