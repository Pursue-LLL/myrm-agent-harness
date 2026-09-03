"""Unit tests for OpenAI Responses API native server-side compaction bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.context_management.infra.native_compaction_bridge import (
    NativeCompactionCoordinator,
    NativeCompactionSidecarStore,
)
from myrm_agent_harness.toolkits.llms.adapters.native_compaction import (
    NativeCompactionItem,
    build_responses_compaction_params,
    is_eligible_native_compaction_route,
    parse_compaction_from_response,
)


def test_is_eligible_native_compaction_route():
    # Eligible cases
    assert is_eligible_native_compaction_route("gpt-5.6")
    assert is_eligible_native_compaction_route("openai/gpt-5.6")
    assert is_eligible_native_compaction_route("gpt-5.4-mini", api_base="https://api.openai.com/v1")
    assert is_eligible_native_compaction_route("codex", custom_llm_provider="openai")

    # Ineligible cases
    assert not is_eligible_native_compaction_route("claude-3-7-sonnet")
    assert not is_eligible_native_compaction_route("deepseek-chat")
    assert not is_eligible_native_compaction_route("gpt-5.6", api_base="https://thirdparty-proxy.com/v1")
    assert not is_eligible_native_compaction_route("gpt-5.6", custom_llm_provider="anthropic")


def test_build_responses_compaction_params():
    params = build_responses_compaction_params(compact_threshold=150_000, store=False)
    assert "context_management" in params
    assert params["context_management"] == [{"type": "compaction", "compact_threshold": 150_000}]
    assert params["store"] is False

    # Floor limit clamping
    params_low = build_responses_compaction_params(compact_threshold=10_000)
    assert params_low["context_management"][0]["compact_threshold"] == 50_000


def test_parse_compaction_from_response():
    # Direct choices format
    resp1 = {
        "model": "gpt-5.6",
        "choices": [
            {
                "delta": {
                    "compaction": {
                        "id": "compact_123",
                        "encrypted_payload": "enc_abc456",
                        "created_at": 1770000000,
                    }
                }
            }
        ],
    }
    item1 = parse_compaction_from_response(resp1)
    assert item1 is not None
    assert item1.item_id == "compact_123"
    assert item1.encrypted_payload == "enc_abc456"

    # Top-level output_items format
    resp2 = {
        "model": "gpt-5.6",
        "output_items": [
            {
                "type": "compaction",
                "id": "compact_789",
                "encrypted_payload": "enc_xyz",
            }
        ],
    }
    item2 = parse_compaction_from_response(resp2)
    assert item2 is not None
    assert item2.item_id == "compact_789"

    # Empty response
    assert parse_compaction_from_response({}) is None


@pytest.mark.asyncio
async def test_native_compaction_sidecar_store_and_self_healing(tmp_path: Path):
    store = NativeCompactionSidecarStore(base_dir=tmp_path)
    session_id = "test_sess_001"

    item = NativeCompactionItem(
        item_id="comp_1",
        encrypted_payload="payload_secret",
        created_at=123456,
        model="gpt-5.6",
    )

    # Save
    await store.save_checkpoint(session_id, item)

    # Load
    loaded = store.load_checkpoint(session_id)
    assert loaded is not None
    assert loaded.item_id == "comp_1"
    assert loaded.encrypted_payload == "payload_secret"

    # Self-healing test: write corrupted json
    corrupted_file = store._get_path(session_id)
    corrupted_file.write_text("invalid json {{{", encoding="utf-8")

    healed = store.load_checkpoint(session_id)
    assert healed is None
    assert not corrupted_file.exists()  # deleted for healing


class DummyPreCompactHook:
    def __init__(self):
        self.called_with = None

    async def recall_and_persist(self, session_id: str) -> None:
        self.called_with = session_id


@pytest.mark.asyncio
async def test_native_compaction_coordinator_lifecycle():
    coordinator = NativeCompactionCoordinator()
    session_id = "sess_coord_01"

    # Clamping margin
    clamped = coordinator.calculate_clamped_server_threshold(
        local_threshold=200_000,
        requested_server_threshold=200_000,
    )
    assert clamped == 170_000  # 200_000 * 0.85

    # Native enabled check
    assert coordinator.is_session_native_enabled(session_id)

    # Rejection recovery
    coordinator.mark_session_rejection_fallback(session_id, reason="400 parameter unsupported")
    assert not coordinator.is_session_native_enabled(session_id)

    # Boundary hook firing
    hook = DummyPreCompactHook()
    comp_item = NativeCompactionItem(item_id="c1", encrypted_payload="p1")
    await coordinator.on_native_compaction_detected("sess_hook", comp_item, pre_compact_hook=hook)
    assert hook.called_with == "sess_hook"


@pytest.mark.asyncio
async def test_native_compaction_edge_cases_and_multi_sessions(tmp_path: Path):
    """Test edge cases: empty session, None hooks, function-based hook, and multiple independent sessions."""
    store = NativeCompactionSidecarStore(base_dir=tmp_path)
    coordinator = NativeCompactionCoordinator(sidecar_store=store)

    # 1. Empty session_id handling
    await store.save_checkpoint("", NativeCompactionItem(item_id="x", encrypted_payload="y"))
    assert store.load_checkpoint("") is None
    store.delete_checkpoint("")

    # 2. Function-based async hook
    hook_called_sess = []

    async def async_fn_hook(session_id: str):
        hook_called_sess.append(session_id)

    item = NativeCompactionItem(item_id="fn_item", encrypted_payload="fn_payload")
    await coordinator.on_native_compaction_detected("sess_fn", item, pre_compact_hook=async_fn_hook)
    assert hook_called_sess == ["sess_fn"]

    # Check sidecar loaded correctly
    loaded = store.load_checkpoint("sess_fn")
    assert loaded is not None
    assert loaded.item_id == "fn_item"

    # 3. None hook edge case (should not throw)
    await coordinator.on_native_compaction_detected("sess_fn", item, pre_compact_hook=None)

    # 4. Independent session degradation
    coordinator.mark_session_rejection_fallback("sess_rejected")
    assert not coordinator.is_session_native_enabled("sess_rejected")
    assert coordinator.is_session_native_enabled("sess_other_active")

    # 5. Delete checkpoint on session reset
    store.delete_checkpoint("sess_fn")
    assert store.load_checkpoint("sess_fn") is None

