# [INPUT]: ContentAddressedStore, ObservationDegradationPipeline, ObservationPackConfig, ObservationPackPagedRecallAndLongOutputHandleArchivalSuite, ObservationRecallTool
# [OUTPUT]: test_observation_pack_suite.py
# [POS]: tests/agent/context_management/test_observation_pack_suite.py

"""Comprehensive test suite for ObservationPack archival, degradation, and recall.

Verifies:
1. Content-addressed storage, SHA-256 handle calculation, and idempotent lossless archival.
2. Two-turn sliding-window full send preservation (FULL_SENDS = 2) and Turn-3 compact degradation.
3. Evidence-preserving reducer receipt exemption protocol (sol_pi_evidence_receipt_v1).
4. On-demand paged recall meta-tool execution with exact line formatting.
5. Batch message transformation and Token savings estimation in the top-level facade suite.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.observation_pack import (
    ContentAddressedStore,
    ObservationDegradationPipeline,
    ObservationHandle,
    ObservationPackConfig,
    ObservationPackPagedRecallAndLongOutputHandleArchivalSuite,
    ObservationPage,
    ObservationRecallTool,
    PackBatchResult,
    TransformDecision,
)


def _generate_large_output(num_lines: int = 500, line_length: int = 40) -> str:
    """Generate deterministic large payload exceeding 10KB."""
    lines = [f"LOG_ENTRY_{i:04d}: System diagnostics payload block - data_{'x' * line_length}" for i in range(num_lines)]
    return "\n".join(lines)


def test_content_addressed_store_and_handle_creation() -> None:
    config = ObservationPackConfig(threshold_bytes=1024, head_bytes=128, tail_bytes=128, default_page_size=20)
    store = ContentAddressedStore(config=config)

    payload = _generate_large_output(num_lines=100, line_length=30)
    handle = store.store(payload)

    # Validate handle properties
    assert handle.obs_id.startswith("obs_")
    assert len(handle.obs_id) == 28  # "obs_" + 24 hex chars
    assert handle.byte_size == len(payload.encode("utf-8"))
    assert handle.line_count == 100
    assert len(handle.head_excerpt.encode("utf-8")) == 128
    assert len(handle.tail_excerpt.encode("utf-8")) == 128

    # Idempotent storage
    handle_second = store.store(payload)
    assert handle_second.obs_id == handle.obs_id
    assert store.total_stored_observations() == 1

    # Lossless retrieval
    retrieved = store.get_content(handle.obs_id)
    assert retrieved == payload

    # Paged retrieval
    page_1 = store.get_page(handle.obs_id, page=1, page_size=25)
    assert page_1 is not None
    assert page_1.page == 1
    assert page_1.total_pages == 4
    assert len(page_1.lines) == 25
    assert page_1.has_more is True

    # Last page
    page_4 = store.get_page(handle.obs_id, page=4, page_size=25)
    assert page_4 is not None
    assert page_4.page == 4
    assert page_4.has_more is False


def test_two_turn_sliding_window_full_sends() -> None:
    config = ObservationPackConfig(threshold_bytes=2048, full_sends=2, head_bytes=64, tail_bytes=64)
    store = ContentAddressedStore(config=config)
    pipeline = ObservationDegradationPipeline(store=store, config=config)

    payload = _generate_large_output(num_lines=80, line_length=40)
    session_id = "test_session_turn"

    # Turn 1: First send carries 100% full payload
    out_1, dec_1 = pipeline.process_observation(payload, session_id=session_id)
    assert dec_1.action == "FULL_SEND_ACTIVE"
    assert out_1 == payload
    assert dec_1.transformed_bytes == dec_1.original_bytes

    # Turn 2: Second send also carries 100% full payload
    out_2, dec_2 = pipeline.process_observation(payload, session_id=session_id)
    assert dec_2.action == "FULL_SEND_ACTIVE"
    assert out_2 == payload

    # Turn 3: Third send triggers degradation to compact excerpt handle
    out_3, dec_3 = pipeline.process_observation(payload, session_id=session_id)
    assert dec_3.action == "DEGRADED_PLACEHOLDER"
    assert out_3 != payload
    assert "[Observation truncated:" in out_3
    assert f"Handle ID: {dec_3.handle_id}" in out_3
    assert "--- HEAD (64B) ---" in out_3
    assert "--- TAIL (64B) ---" in out_3
    assert dec_3.transformed_bytes < dec_3.original_bytes


def test_evidence_receipt_exemption_protocol() -> None:
    config = ObservationPackConfig(threshold_bytes=512, full_sends=2)
    store = ContentAddressedStore(config=config)
    pipeline = ObservationDegradationPipeline(store=store, config=config)

    receipt_prefix = "sol_pi_evidence_receipt_v1"
    receipt_body = _generate_large_output(num_lines=50, line_length=30)
    verified_receipt = f"{receipt_prefix}: Verified compiler diagnostics trace\n{receipt_body}"

    # Verify receipt is never compacted regardless of send count
    for _ in range(5):
        out, dec = pipeline.process_observation(verified_receipt, session_id="receipt_sess")
        assert dec.action == "EXEMPT_RECEIPT"
        assert out == verified_receipt
        assert dec.transformed_bytes == dec.original_bytes


def test_paged_recall_meta_tool_execution() -> None:
    config = ObservationPackConfig(threshold_bytes=512, default_page_size=10)
    store = ContentAddressedStore(config=config)
    tool = ObservationRecallTool(store=store)

    payload = _generate_large_output(num_lines=25, line_length=20)
    handle = store.store(payload)

    # Tool spec schema verification
    spec = tool.get_tool_spec()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "recall_observation"

    # Page 1 execution
    p1_output = tool.execute(handle.obs_id, page=1, page_size=10)
    assert f"[Observation {handle.obs_id} | Page 1/3 (Lines 1-10 of 25)]" in p1_output
    assert "    1 | LOG_ENTRY_0000" in p1_output
    assert "Call recall_observation" in p1_output

    # Page 3 (final page) execution
    p3_output = tool.execute(handle.obs_id, page=3, page_size=10)
    assert f"[Observation {handle.obs_id} | Page 3/3 (Lines 21-25 of 25)]" in p3_output
    assert "[End of observation]" in p3_output

    # Nonexistent handle error handling
    missing_output = tool.execute("obs_nonexistent_handle", page=1)
    assert "[Error: Observation 'obs_nonexistent_handle' not found in local store" in missing_output


def test_suite_batch_transformation_and_tokenomics() -> None:
    suite = ObservationPackPagedRecallAndLongOutputHandleArchivalSuite.create(
        threshold_bytes=1024,
        full_sends=2,
    )

    large_tool_output = _generate_large_output(num_lines=150, line_length=35)
    messages = [
        {"role": "user", "content": "Run tests and summarize findings."},
        {"role": "assistant", "content": "Executing test runner..."},
        {"role": "tool", "content": large_tool_output},
    ]

    session_id = "e2e_session_audit"

    # Turn 1
    res_1 = suite.transform_turn_messages(messages, session_id=session_id)
    assert res_1.degraded_count == 0
    assert res_1.bytes_saved == 0

    # Turn 2
    res_2 = suite.transform_turn_messages(messages, session_id=session_id)
    assert res_2.degraded_count == 0
    assert res_2.bytes_saved == 0

    # Turn 3: Tool observation is degraded to compact handle
    res_3 = suite.transform_turn_messages(messages, session_id=session_id)
    assert res_3.degraded_count == 1
    assert res_3.bytes_saved > 5000
    assert res_3.tokens_saved_estimate == res_3.bytes_saved // 4
    assert "[Observation truncated:" in res_3.messages[2]["content"]

    # Retrieve raw content from suite
    handle_id = res_3.decisions[0].handle_id
    assert handle_id is not None
    assert suite.get_raw_observation(handle_id) == large_tool_output

    # Recall via suite
    recall_res = suite.recall_observation(handle_id, page=1, page_size=15)
    assert f"[Observation {handle_id} | Page 1/" in recall_res
