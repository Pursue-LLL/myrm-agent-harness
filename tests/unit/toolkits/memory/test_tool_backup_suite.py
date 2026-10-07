"""[POS]: tests/unit/toolkits/memory/test_tool_backup_suite.py
[INPUT]: Unit test suite for durable tool use backup index, truncation, and audit queries.
[OUTPUT]: Pytest test cases verifying record, retrieval, query, stats, and fail-safe isolation.
"""

import sqlite3

from myrm_agent_harness.toolkits.memory.tool_backup import (
    ToolUseBackupRecorder,
    ToolUseBackupService,
    ToolUseQueryFilter,
    ToolUseRecord,
    ToolUseStats,
    ToolUseStatus,
)


def test_tool_use_record_and_get() -> None:
    service = ToolUseBackupService(db_path=":memory:")
    session_id = "sess_audit_001"
    raw_input = '{"path": "config.yaml", "mode": "read"}'
    raw_output = "database_url: postgres://localhost:5432"

    record = service.record_tool_use(
        session_id=session_id,
        tool_name="read_file",
        raw_input=raw_input,
        raw_output=raw_output,
        tool_call_id="call_99182",
        status=ToolUseStatus.SUCCESS,
        duration_ms=42.5,
        metadata={"caller": "l2_agent"},
    )

    assert record is not None
    assert record.session_id == session_id
    assert record.tool_name == "read_file"
    assert record.is_truncated is False
    assert record.duration_ms == 42.5
    assert record.metadata.get("caller") == "l2_agent"

    # By-reference lookup
    fetched = service.get_tool_use(record.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.raw_input == raw_input
    assert fetched.raw_output == raw_output
    service.close()


def test_large_output_truncation_protection() -> None:
    # Set max limit to 1000 bytes
    service = ToolUseBackupService(db_path=":memory:", max_output_bytes=1000)
    huge_output = "X" * 5000

    record = service.record_tool_use(
        session_id="sess_huge",
        tool_name="run_bash",
        raw_input="cat big.log",
        raw_output=huge_output,
        status=ToolUseStatus.SUCCESS,
        duration_ms=120.0,
    )

    assert record is not None
    assert record.is_truncated is True
    assert record.original_output_bytes == 5000
    assert "[TRUNCATED" in record.raw_output
    assert len(record.raw_output.encode("utf-8")) < 2000

    fetched = service.get_tool_use(record.id)
    assert fetched is not None
    assert fetched.is_truncated is True
    service.close()


def test_filtered_query_and_pagination() -> None:
    service = ToolUseBackupService(db_path=":memory:")
    base_epoch = 1_700_000_000.0

    for i in range(10):
        t_name = "git_commit" if i % 2 == 0 else "bash_exec"
        stat = ToolUseStatus.SUCCESS if i < 8 else ToolUseStatus.ERROR
        service.record_tool_use(
            session_id=f"sess_{i % 2}",
            tool_name=t_name,
            raw_input=f"cmd_{i}",
            raw_output=f"out_{i}",
            status=stat,
            duration_ms=10.0 * (i + 1),
            created_at_epoch=base_epoch + i,
        )

    # 1. Filter by session_id
    res_sess0 = service.query_tool_uses(ToolUseQueryFilter(session_id="sess_0", limit=20))
    assert len(res_sess0) == 5
    assert all(r.session_id == "sess_0" for r in res_sess0)

    # 2. Filter by tool_name
    res_git = service.query_tool_uses(ToolUseQueryFilter(tool_name="git_commit", limit=20))
    assert len(res_git) == 5
    assert all(r.tool_name == "git_commit" for r in res_git)

    # 3. Filter by error status
    res_err = service.query_tool_uses(ToolUseQueryFilter(status=ToolUseStatus.ERROR, limit=20))
    assert len(res_err) == 2

    # 4. Pagination
    res_page = service.query_tool_uses(ToolUseQueryFilter(limit=3, offset=0))
    assert len(res_page) == 3
    service.close()


def test_audit_statistics_computation() -> None:
    service = ToolUseBackupService(db_path=":memory:")

    # Initial stats on empty store
    empty_stats = service.get_stats()
    assert empty_stats.total_tool_uses == 0
    assert empty_stats.success_count == 0
    assert empty_stats.avg_duration_ms == 0.0

    # Insert 3 records
    service.record_tool_use("s1", "tool_a", "in1", "out1", status=ToolUseStatus.SUCCESS, duration_ms=10.0)
    service.record_tool_use("s1", "tool_b", "in2", "out2", status=ToolUseStatus.SUCCESS, duration_ms=20.0)
    service.record_tool_use("s2", "tool_c", "in3", "out3", status=ToolUseStatus.ERROR, duration_ms=30.0)

    # Global stats
    global_stats: ToolUseStats = service.get_stats()
    assert global_stats.total_tool_uses == 3
    assert global_stats.success_count == 2
    assert global_stats.error_count == 1
    assert global_stats.avg_duration_ms == 20.0

    # Session s1 stats
    s1_stats: ToolUseStats = service.get_stats(session_id="s1")
    assert s1_stats.total_tool_uses == 2
    assert s1_stats.success_count == 2
    assert s1_stats.avg_duration_ms == 15.0

    # Purge s1 session tool uses
    deleted = service.purge_session(session_id="s1")
    assert deleted == 2
    assert service.get_stats(session_id="s1").total_tool_uses == 0
    assert service.get_stats().total_tool_uses == 1
    service.close()


def test_fail_safe_isolation_on_database_error() -> None:
    # Closed connection must not crash the caller
    conn = sqlite3.connect(":memory:")
    recorder = ToolUseBackupRecorder(conn=conn)
    conn.close()

    # Execution must return None gracefully without raising exceptions
    res: ToolUseRecord | None = recorder.record_tool_use(
        session_id="sess_safe",
        tool_name="critical_tool",
        raw_input="delete_all",
        raw_output="forbidden",
        status=ToolUseStatus.ERROR,
    )
    assert res is None
