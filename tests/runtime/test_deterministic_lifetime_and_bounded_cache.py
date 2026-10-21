"""Unit tests for Deterministic Lifetime and Bounded Cache Memory Sentinel Suite."""

from __future__ import annotations

import tempfile
import time

from myrm_agent_harness.runtime.memory_sentinel import (
    IdleSessionFreezer,
    SpillToVolumeHydrator,
    ThreeDimensionalBoundedCache,
)


def test_bounded_cache_ttl_and_lru_eviction() -> None:
    """Verify bounded cache enforces Time-To-Live expiration and LRU capacity limits."""
    # 1. Test TTL Expiration
    cache = ThreeDimensionalBoundedCache(max_items=10, max_bytes=1024 * 1024, default_ttl_s=0.05)
    cache.set("key_temp", "temporary_value")
    assert cache.get("key_temp") == "temporary_value"

    time.sleep(0.08)
    assert cache.get("key_temp") is None  # Evicted due to TTL

    # 2. Test LRU Capacity Limit (max_items=2)
    lru_cache = ThreeDimensionalBoundedCache(max_items=2, max_bytes=1024 * 1024, default_ttl_s=100.0)
    lru_cache.set("a", "val_a")
    lru_cache.set("b", "val_b")

    # Touch 'a' to make 'b' the least recently used
    assert lru_cache.get("a") == "val_a"

    # Insert 'c', which should push out 'b'
    lru_cache.set("c", "val_c")
    assert lru_cache.get("b") is None
    assert lru_cache.get("a") == "val_a"
    assert lru_cache.get("c") == "val_c"


def test_bounded_cache_byte_cap_limit() -> None:
    """Verify bounded cache strictly respects the heap byte-cap limit."""
    # Byte limit = 100 bytes
    cache = ThreeDimensionalBoundedCache(max_items=100, max_bytes=100, default_ttl_s=100.0)

    payload_a = "x" * 60  # 60 bytes
    payload_b = "y" * 60  # 60 bytes

    cache.set("item_a", payload_a)
    stats_1 = cache.get_stats()
    assert stats_1.current_bytes == 60

    # Adding payload_b (60 bytes) exceeds 100 bytes limit (60+60=120 > 100)
    # Must evict item_a to accommodate item_b
    cache.set("item_b", payload_b)
    stats_2 = cache.get_stats()
    assert stats_2.current_bytes == 60
    assert cache.get("item_a") is None
    assert cache.get("item_b") == payload_b
    assert stats_2.eviction_count == 1


def test_spill_to_volume_dehydration_and_hydration() -> None:
    """Verify large payloads are compressed to disk storage and hydrated on-demand."""
    with tempfile.TemporaryDirectory() as tmpdir:
        hydrator = SpillToVolumeHydrator(storage_dir=tmpdir, threshold_bytes=100)

        # 1. Payload under threshold stays in memory
        small_text = "Small in-memory payload"
        dehydrated_small, val_small = hydrator.dehydrate_if_large(small_text)
        assert dehydrated_small is False
        assert val_small == small_text

        # 2. Large payload exceeds threshold -> dehydrated to disk
        large_text = "Extremely large tool output " * 50  # ~1400 bytes
        dehydrated_large, handle = hydrator.dehydrate_if_large(large_text, prefix_hint="scrape")
        assert dehydrated_large is True
        assert not isinstance(handle, str)
        assert handle.raw_size_bytes > 100
        assert handle.disk_path.exists()
        assert len(handle.preview_snippet) <= 200

        # 3. Streamingly hydrate on demand
        restored = hydrator.hydrate(handle)
        assert restored == large_text

        # 4. Partial hydration
        preview_10 = hydrator.hydrate(handle, max_chars=10)
        assert preview_10 == large_text[:10]

        # 5. Fault tolerance when file is deleted externally
        hydrator.delete_spill(handle)
        fallback = hydrator.hydrate(handle)
        assert "[DEHYDRATED_CONTENT_UNAVAILABLE" in fallback
        assert handle.preview_snippet in fallback


def test_idle_session_freezer_and_wake() -> None:
    """Verify idle sessions are unloaded from memory to disk and rehydrated on access."""
    with tempfile.TemporaryDirectory() as tmpdir:
        freezer = IdleSessionFreezer(storage_dir=tmpdir)
        session_id = "sess_customer_1001"
        messages = [
            {"role": "user", "content": "Help with deployment"},
            {"role": "assistant", "content": "Checking logs now"},
        ]

        freezer.set_session(session_id, messages)
        assert freezer.get_resident_count() == 1

        # Simulate idle timeout expiration (0.05s)
        time.sleep(0.08)
        frozen_records = freezer.sweep_and_freeze_idle_sessions(idle_timeout_s=0.05)
        assert len(frozen_records) == 1
        assert frozen_records[0].session_id == session_id
        assert frozen_records[0].storage_file.exists()

        # Session must be completely evicted from resident heap memory
        assert freezer.get_resident_count() == 0

        # When customer resumes chatting, session is transparently woken up and rehydrated
        woken_messages = freezer.get_or_wake_session(session_id)
        assert woken_messages is not None
        assert len(woken_messages) == 2
        assert woken_messages[0]["content"] == "Help with deployment"
        assert freezer.get_resident_count() == 1


def test_memory_governance_markdown_card() -> None:
    """Verify GitHub Flavored Markdown card rendering for memory sentinel telemetries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        freezer = IdleSessionFreezer(storage_dir=tmpdir)
        cache = ThreeDimensionalBoundedCache(max_items=10, max_bytes=100)

        # Trigger evictions
        cache.set("k1", "v" * 80)
        cache.set("k2", "v" * 80)

        stats = cache.get_stats()
        card = freezer.render_memory_governance_markdown(stats)

        assert "### 🧠 确定性内存生命周期与有界缓存防爆看板" in card
        assert "> [!NOTE]" in card
        assert "**[防爆机制生效中]**" in card
