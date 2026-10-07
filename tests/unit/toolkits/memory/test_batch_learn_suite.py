"""[POS]: tests/unit/toolkits/memory/test_batch_learn_suite.py
[INPUT]: None.
[OUTPUT]: Comprehensive unit tests for namespaced ID provenance, chunk retry resilience, and item undo.
"""

from pathlib import Path

from myrm_agent_harness.toolkits.memory.batch_learn import (
    BatchMemoryLearningMetaTools,
    BatchMemoryLearningService,
    BatchRawChunk,
    ChunkProcessingStatus,
    ChunkRetryConfig,
    ItemProvenanceStatus,
    NamespacedIdGenerator,
    ResilientChunkRetryExecutor,
    TransientMemoryProcessingError,
)


def test_namespaced_id_generator_roundtrip() -> None:
    """Verify deterministic namespaced ID generation, parsing, and format validation."""
    content = "User prefers concise Python syntax without any types"
    ns_id = NamespacedIdGenerator.generate(
        scope="proj-alpha",
        sub_scope="user-42",
        category="coding_preference",
        content=content,
    )

    assert ns_id.scope == "proj-alpha"
    assert ns_id.sub_scope == "user-42"
    assert ns_id.category == "coding_preference"
    assert len(ns_id.content_fingerprint) == 16
    assert ns_id.full_id.startswith("mem:proj-alpha:user-42:coding_preference:")

    # Validate parsing
    parsed = NamespacedIdGenerator.parse(ns_id.full_id)
    assert parsed is not None
    assert parsed.scope == "proj-alpha"
    assert parsed.sub_scope == "user-42"
    assert parsed.category == "coding_preference"
    assert parsed.content_fingerprint == ns_id.content_fingerprint

    # Validate syntax check
    assert NamespacedIdGenerator.is_valid(ns_id.full_id) is True
    assert NamespacedIdGenerator.is_valid("invalid_id_format") is False
    assert NamespacedIdGenerator.is_valid("mem:only:two_parts") is False


def test_resilient_executor_transient_retry_and_recovery() -> None:
    """Verify executor recovers from transient errors via backoff and captures diagnostic attempts."""
    config = ChunkRetryConfig(
        max_retries=3,
        initial_delay_sec=0.01,
        backoff_factor=1.5,
        enable_jitter=False,
    )
    executor = ResilientChunkRetryExecutor(config=config)

    chunk = BatchRawChunk(chunk_index=0, raw_text="System documentation on memory bus")

    call_count = 0

    def flaky_processor(c: BatchRawChunk) -> list[str]:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise TransientMemoryProcessingError("Simulated HTTP 429 rate limit")
        return ["Extracted rule: memory bus must be thread-safe"]

    results, record = executor.execute_chunk(chunk, flaky_processor)

    assert len(results) == 1
    assert "memory bus must be thread-safe" in results[0]
    assert record.status == ChunkProcessingStatus.RETRIED_SUCCESS
    assert record.attempt_count == 3
    assert record.chunk_index == 0


def test_resilient_executor_permanent_error_fail_fast() -> None:
    """Verify executor fails immediately without retries when encountering permanent errors."""
    config = ChunkRetryConfig(max_retries=3, initial_delay_sec=0.01)
    executor = ResilientChunkRetryExecutor(config=config)

    chunk = BatchRawChunk(chunk_index=1, raw_text="Corrupted chunk payload")

    call_count = 0

    def invalid_processor(c: BatchRawChunk) -> list[str]:
        nonlocal call_count
        call_count += 1
        raise ValueError("Invalid schema: cannot parse unescaped character")

    results, record = executor.execute_chunk(chunk, invalid_processor)

    assert len(results) == 0
    assert record.status == ChunkProcessingStatus.FAILED_PERMANENT
    assert record.attempt_count == 1
    assert "ValueError" in (record.error_message or "")


def test_batch_service_learning_provenance_and_undo(tmp_path: Path) -> None:
    """Verify batch learning persistence, item-level ID mapping, and undo capability."""
    db_file = tmp_path / "test_batch_learn.db"
    service = BatchMemoryLearningService(db_path=db_file)

    chunks = [
        BatchRawChunk(
            chunk_index=0,
            raw_text="- User drinks espresso every morning.\n- User works in timezone UTC+8.",
        ),
        BatchRawChunk(
            chunk_index=1,
            raw_text="- Strictly disallow any usage of typing.Any in codebase.",
        ),
    ]

    report = service.learn_batch(
        chunks=chunks,
        scope="workspace_1",
        sub_scope="dev_agent",
        category="rules",
    )

    assert report.total_chunks == 2
    assert report.successful_chunks == 2
    assert report.failed_chunks == 0
    assert report.total_items_learned == 3
    assert len(report.items) == 3

    # Verify each item has a unique namespaced ID
    all_ids = [it.namespaced_id for it in report.items]
    assert len(set(all_ids)) == 3
    for it in report.items:
        assert it.namespaced_id.startswith("mem:workspace_1:dev_agent:rules:")
        assert it.status == ItemProvenanceStatus.ACTIVE

    # Test single item undo
    target_item = report.items[0]
    undo_ok = service.undo_item_by_namespaced_id(target_item.namespaced_id)
    assert undo_ok is True

    # Re-fetch item to verify status changed to REVOKED
    fetched = service.get_item_by_namespaced_id(target_item.namespaced_id)
    assert fetched is not None
    assert fetched.status == ItemProvenanceStatus.REVOKED

    # Repeated undo should be idempotent / return False
    undo_again = service.undo_item_by_namespaced_id(target_item.namespaced_id)
    assert undo_again is False

    # Other items remain ACTIVE
    other_item = service.get_item_by_namespaced_id(report.items[1].namespaced_id)
    assert other_item is not None
    assert other_item.status == ItemProvenanceStatus.ACTIVE

    service.close()


def test_meta_tools_integration(tmp_path: Path) -> None:
    """Verify Agent meta-tools expose batch extraction, inspection, and undo seamlessly."""
    db_file = tmp_path / "meta_tools_batch.db"
    service = BatchMemoryLearningService(db_path=db_file)
    tools = BatchMemoryLearningMetaTools(service=service)

    raw_chunks = [
        {"chunk_index": 0, "raw_text": "- Always enforce PEP8 compliance for Python."},
        {"chunk_index": 1, "raw_text": "- Max file size should strictly be under 400 lines."},
    ]

    learn_resp = tools.batch_learn_from_chunks(
        chunks=raw_chunks,
        scope="project_a",
        sub_scope="agent_core",
        category="standards",
    )

    assert learn_resp["total_chunks"] == 2
    assert learn_resp["total_items_learned"] == 2
    items = learn_resp["items"]
    assert isinstance(items, list)
    assert len(items) == 2

    first_id = str(items[0]["namespaced_id"])
    inspect_resp = tools.inspect_batch_learned_item(first_id)
    assert inspect_resp is not None
    assert inspect_resp["namespaced_id"] == first_id
    assert inspect_resp["status"] == "active"

    # Revoke via tools
    undo_resp = tools.undo_learned_memory_item(first_id)
    assert undo_resp["success"] is True

    # Re-inspect to verify revoked status
    inspect_after = tools.inspect_batch_learned_item(first_id)
    assert inspect_after is not None
    assert inspect_after["status"] == "revoked"

    service.close()
