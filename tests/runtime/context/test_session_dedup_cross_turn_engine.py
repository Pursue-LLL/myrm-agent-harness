"""Unit test suite for SessionDedupCrossTurnContentAddressingAndRetrieveMarkerEngine (Item 108).

Verifies the first layer of the Tokenomics 12-engine compression stack:
- Three-level logical boundary content chunking (System Prompt, Message Turns, Heavy Tool Payloads).
- SHA-256 O(1) content addressing and cross-turn fingerprint deduplication.
- Lightweight [RetrieveMarker: ...] placeholder injection.
- On-demand CCR retrieval hydration (lossless recovery).
- Multi-turn (20-turn) benchmark achieving >= 75% token reduction on repeated heavy payloads.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.session_dedup_processor import (
    SessionDedupProcessor,
)
from myrm_agent_harness.runtime.context.session_dedup_types import (
    BlockChunkLevel,
    SessionDedupConfig,
)


def test_three_level_chunking_classification() -> None:
    """Verify that message roles are accurately classified into chunk levels."""
    processor = SessionDedupProcessor()

    assert processor._classify_chunk_level("system") == BlockChunkLevel.SYSTEM_PROMPT
    assert processor._classify_chunk_level("sys") == BlockChunkLevel.SYSTEM_PROMPT
    assert processor._classify_chunk_level("user") == BlockChunkLevel.MESSAGE_TURN
    assert processor._classify_chunk_level("assistant") == BlockChunkLevel.MESSAGE_TURN
    assert processor._classify_chunk_level("tool") == BlockChunkLevel.TOOL_PAYLOAD
    assert processor._classify_chunk_level("tool_result") == BlockChunkLevel.TOOL_PAYLOAD
    assert processor._classify_chunk_level("observation") == BlockChunkLevel.TOOL_PAYLOAD


def test_cross_turn_content_addressing_and_marker_injection() -> None:
    """Verify that heavy tool outputs repeated across turns are replaced by retrieve markers."""
    config = SessionDedupConfig(min_payload_chars=100)
    processor = SessionDedupProcessor(config=config)

    heavy_tool_output = (
        "def query_database(sql: str) -> list[dict]:\n"
        "    # Verbatim long query return schema\n"
        "    records = [{'id': i, 'status': 'ACTIVE', 'value': 42 * i} for i in range(50)]\n"
        "    return records\n"
    ) * 5

    # Turn 1: First appearance of tool output -> kept inline
    turn1_msgs = [
        {"role": "user", "content": "Fetch database query function"},
        {"role": "tool", "content": heavy_tool_output},
    ]
    packages_t1, report_t1 = processor.process_turn_messages(turn1_msgs, current_turn=1)

    assert report_t1.markers_injected == 0
    assert report_t1.tokens_saved == 0
    assert packages_t1[1].is_deduped is False
    assert packages_t1[1].content == heavy_tool_output

    # Turn 2: Second appearance in a later turn -> replaced with [RetrieveMarker: ...]
    turn2_msgs = [
        {"role": "user", "content": "Review the exact same query function again"},
        {"role": "tool", "content": heavy_tool_output},
    ]
    packages_t2, report_t2 = processor.process_turn_messages(turn2_msgs, current_turn=2)

    assert report_t2.markers_injected == 1
    assert report_t2.tokens_saved > 100
    assert packages_t2[1].is_deduped is True
    assert "[RetrieveMarker:" in packages_t2[1].content
    assert "source=tool" in packages_t2[1].content


def test_lossless_retrieval_marker_hydration() -> None:
    """Verify that retrieve markers are 100% losslessly expanded back into verbatim content."""
    config = SessionDedupConfig(min_payload_chars=80)
    processor = SessionDedupProcessor(config=config)

    verbatim_text = "API_KEY_CONFIG = 'SECRET_VALUE_12345'\nDATABASE_URL = 'postgres://user:pass@localhost:5432/db'\n" * 4

    # Index in Turn 1
    processor.process_turn_messages([{"role": "tool", "content": verbatim_text}], current_turn=1)

    # Dedup in Turn 2
    packages_t2, _ = processor.process_turn_messages([{"role": "tool", "content": verbatim_text}], current_turn=2)
    marker_placeholder = packages_t2[0].content
    assert "[RetrieveMarker:" in marker_placeholder

    # Hydrate marker
    hydrated = processor.hydrate_retrieve_markers(marker_placeholder)
    assert hydrated == verbatim_text


def test_twenty_turn_benchmark_achieves_seventy_five_percent_savings() -> None:
    """Verify 20-turn session with repeated heavy outputs achieves >= 75% token reduction."""
    config = SessionDedupConfig(min_payload_chars=120)
    processor = SessionDedupProcessor(config=config)

    heavy_file_a = "CLASS_A_DEFINITION = 'Component A with extensive docstrings and methods'\n" * 20
    heavy_file_b = "CLASS_B_DEFINITION = 'Component B with database drivers and network handlers'\n" * 20

    # 20 turns alternating queries on heavy_file_a and heavy_file_b
    for turn in range(1, 21):
        target_payload = heavy_file_a if turn % 2 == 1 else heavy_file_b
        msgs = [
            {"role": "user", "content": f"Turn {turn} request inspection"},
            {"role": "tool", "content": target_payload},
            {"role": "assistant", "content": f"Turn {turn} verified"},
        ]
        processor.process_turn_messages(msgs, current_turn=turn)

    overall_report = processor.get_overall_savings_report(current_turn=20)

    # In 20 turns, turns 3 through 20 will all deduplicate the repeated files
    assert overall_report.markers_injected >= 18
    # Overall savings ratio must be >= 75%
    assert overall_report.savings_ratio >= 0.75
    assert overall_report.tokens_saved > 1000
