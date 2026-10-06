"""Unit tests for Session-Dedup and Content-Addressed CCR Context Archival.

Covers:
1. ContentAddressedDedupStore SHA-256 indexing, retrieval, and LRU eviction
2. Cross-turn verbatim file/output deduplication (Session-Dedup)
3. Content mutation breaking deduplication and forcing fresh updates
4. Oversized content archival into CCR Retrieve Markers
5. On-demand artifact retrieval and marker expansion
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.ccr_context_archival_transformer import (
    CCRContextArchivalTransformer,
)
from myrm_agent_harness.runtime.context.content_addressed_dedup_store import (
    ContentAddressedDedupStore,
)
from myrm_agent_harness.runtime.context.content_addressed_dedup_types import (
    DedupConfig,
    DedupContentType,
)


def test_content_addressed_store_store_and_retrieve() -> None:
    """Verify SHA-256 content indexing and verbatim retrieval."""
    store = ContentAddressedDedupStore(max_cached_chunks=10)

    sample_content = (
        "export interface UserProfile {\n"
        "    id: string;\n"
        "    username: string;\n"
        "    email: string;\n"
        "}"
    )

    meta = store.store_content(
        content=sample_content,
        content_type=DedupContentType.FILE_CONTENT,
        source_hint="src/types/user.ts",
    )

    assert meta.marker_id.startswith("chunk_")
    assert len(meta.content_hash) == 64
    assert meta.line_count == 5

    # Retrieve by marker_id
    retrieved_by_id = store.retrieve_content(meta.marker_id)
    assert retrieved_by_id == sample_content

    # Retrieve by full sha256 hash
    retrieved_by_hash = store.retrieve_content(meta.content_hash)
    assert retrieved_by_hash == sample_content


def test_session_dedup_cross_turn_and_mutation() -> None:
    """Verify identical content across turns is replaced by a Content-Ref, breaking on mutation."""
    config = DedupConfig(min_dedup_chars=50)
    transformer = CCRContextArchivalTransformer(config=config)

    file_content_v1 = (
        "# Configuration File\n"
        "database_url: postgres://localhost:5432/db\n"
        "max_connections: 50\n"
        "timeout_seconds: 30\n"
        "debug_mode: false\n"
    )

    # Turn 1: First observation of config file -> kept inline
    res_turn_1 = transformer.transform_turn_content(
        content=file_content_v1,
        current_turn=1,
        source_hint="config.yaml",
        content_type=DedupContentType.FILE_CONTENT,
    )
    assert res_turn_1.deduped_count == 0
    assert "[Content-Ref:" not in res_turn_1.transformed_content
    assert res_turn_1.transformed_content == file_content_v1

    # Turn 2: Repeated observation of identical content -> deduplicated into Content-Ref
    res_turn_2 = transformer.transform_turn_content(
        content=file_content_v1,
        current_turn=2,
        source_hint="config.yaml",
        content_type=DedupContentType.FILE_CONTENT,
    )
    assert res_turn_2.deduped_count == 1
    assert "[Content-Ref:" in res_turn_2.transformed_content
    assert "unchanged since turn 1]" in res_turn_2.transformed_content
    assert "config.yaml" in res_turn_2.transformed_content
    assert res_turn_2.reduction_ratio > 0.30

    # Turn 3: Content changed (mutation) -> must break deduplication and show latest content
    file_content_v2 = file_content_v1.replace("max_connections: 50", "max_connections: 100")
    res_turn_3 = transformer.transform_turn_content(
        content=file_content_v2,
        current_turn=3,
        source_hint="config.yaml",
        content_type=DedupContentType.FILE_CONTENT,
    )
    assert res_turn_3.deduped_count == 0
    assert "[Content-Ref:" not in res_turn_3.transformed_content
    assert "max_connections: 100" in res_turn_3.transformed_content


def test_oversized_content_ccr_marker_archival() -> None:
    """Verify oversized log or document content is replaced by a CCR Retrieve Marker."""
    config = DedupConfig(max_inline_lines=20, min_dedup_chars=50)
    transformer = CCRContextArchivalTransformer(config=config)

    # Generate a long 50-line log output
    long_log = "\n".join(
        f"[INFO 2026-10-07 10:{i:02d}:00] Processing worker event job #{i * 10}"
        for i in range(50)
    )

    res = transformer.transform_turn_content(
        content=long_log,
        current_turn=1,
        source_hint="celery_worker.log",
        content_type=DedupContentType.TOOL_OUTPUT,
    )

    assert res.archived_count == 1
    assert res.deduped_count == 0
    assert "[Retrieve-Marker:" in res.transformed_content
    assert "use retrieve_artifact(" in res.transformed_content
    assert res.reduction_ratio > 0.80

    marker_meta = res.markers_created[0]
    assert marker_meta.source_hint == "celery_worker.log"
    assert marker_meta.line_count == 50

    # On-demand expansion using retrieve_artifact
    retrieved = transformer.retrieve_artifact(marker_meta.marker_id)
    assert retrieved == long_log


def test_expand_retrieve_markers_utility() -> None:
    """Verify helper expands embedded markers back to original text."""
    store = ContentAddressedDedupStore()
    transformer = CCRContextArchivalTransformer(store=store)

    text_to_archive = "Very long payload that was archived to external store."
    meta = store.store_content(
        content=text_to_archive,
        content_type=DedupContentType.ARBITRARY_CHUNK,
        source_hint="doc.txt",
    )

    wrapped_prompt = f"Summary: before {meta.format_marker_directive()} after."
    expanded = transformer.expand_retrieve_markers(wrapped_prompt)

    assert text_to_archive in expanded
    assert "Summary: before" in expanded
    assert "after." in expanded


def test_lru_cache_capacity_eviction() -> None:
    """Verify least-recently-used chunk eviction when exceeding max cache limit."""
    store = ContentAddressedDedupStore(max_cached_chunks=2)

    chunk_1 = store.store_content("first chunk content", DedupContentType.ARBITRARY_CHUNK)
    chunk_2 = store.store_content("second chunk content", DedupContentType.ARBITRARY_CHUNK)
    assert store.retrieve_content(chunk_1.marker_id) is not None

    # Adding third chunk should evict chunk_2 (since chunk_1 was recently retrieved)
    chunk_3 = store.store_content("third chunk content", DedupContentType.ARBITRARY_CHUNK)

    assert store.retrieve_content(chunk_1.marker_id) is not None
    assert store.retrieve_content(chunk_3.marker_id) is not None
    assert store.retrieve_content(chunk_2.marker_id) is None
