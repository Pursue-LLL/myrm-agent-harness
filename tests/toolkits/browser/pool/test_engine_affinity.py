"""Unit tests for EngineAffinityStore.

Covers: construction, get/record/clear, TTL expiration, LRU eviction,
file persistence (load/flush), singleton accessor, and edge cases
(corrupt JSON, invalid engine value, missing directory).
"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine
from myrm_agent_harness.toolkits.browser.pool.engine_affinity import (
    EngineAffinityStore,
    _MAX_ENTRIES,
    _TTL_SECONDS,
    get_engine_affinity_store,
)


@pytest.fixture()
def store_dir(tmp_path: object) -> str:
    """Provide a temp MYRM_DATA_DIR and reset the singleton between tests."""
    import myrm_agent_harness.toolkits.browser.pool.engine_affinity as mod

    old_global = mod._global_store
    mod._global_store = None

    data_dir = str(tmp_path)
    with patch.dict(os.environ, {"MYRM_DATA_DIR": data_dir}):
        yield data_dir

    mod._global_store = old_global


def _json_path(data_dir: str) -> str:
    return os.path.join(data_dir, "browser", "engine_affinity.json")


# ── Construction ─────────────────────────────────────────────────────

class TestConstruction:
    def test_fresh_store_empty(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        assert store.get("example.com") is None

    def test_lazy_load_flag(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        assert not store._loaded
        store.get("x.com")
        assert store._loaded


# ── Record & Get ─────────────────────────────────────────────────────

class TestRecordAndGet:
    def test_record_then_get(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        store.record("cloudflare.com", BrowserEngine.FIREFOX_CAMOUFOX)
        result = store.get("cloudflare.com")
        assert result is BrowserEngine.FIREFOX_CAMOUFOX

    def test_get_miss(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        assert store.get("unknown.org") is None

    def test_record_overwrites(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        store.record("site.com", BrowserEngine.CHROMIUM_PATCHRIGHT)
        store.record("site.com", BrowserEngine.FIREFOX_CAMOUFOX)
        assert store.get("site.com") is BrowserEngine.FIREFOX_CAMOUFOX


# ── Clear ────────────────────────────────────────────────────────────

class TestClear:
    def test_clear_existing(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        store.record("site.com", BrowserEngine.FIREFOX_CAMOUFOX)
        store.clear("site.com")
        assert store.get("site.com") is None

    def test_clear_nonexistent_is_noop(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        store.clear("nope.com")


# ── TTL Expiration ───────────────────────────────────────────────────

class TestTTL:
    def test_expired_entry_returns_none(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        store.record("old.com", BrowserEngine.FIREFOX_CAMOUFOX)
        expired_ts = time.time() - _TTL_SECONDS - 1
        store._cache["old.com"] = (BrowserEngine.FIREFOX_CAMOUFOX.value, expired_ts)

        assert store.get("old.com") is None

    def test_expired_entry_removed_from_cache(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        store.record("old.com", BrowserEngine.FIREFOX_CAMOUFOX)
        expired_ts = time.time() - _TTL_SECONDS - 1
        store._cache["old.com"] = (BrowserEngine.FIREFOX_CAMOUFOX.value, expired_ts)

        store.get("old.com")
        assert "old.com" not in store._cache


# ── LRU Eviction ─────────────────────────────────────────────────────

class TestLRUEviction:
    def test_evicts_oldest_when_exceeding_max(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        store._loaded = True
        now = time.time()

        for i in range(_MAX_ENTRIES):
            store._cache[f"d{i}.com"] = (BrowserEngine.FIREFOX_CAMOUFOX.value, now + i)
        store._dirty = False

        store.record("overflow.com", BrowserEngine.FIREFOX_CAMOUFOX)
        assert len(store._cache) <= _MAX_ENTRIES
        assert "d0.com" not in store._cache
        assert store.get("overflow.com") is BrowserEngine.FIREFOX_CAMOUFOX


# ── File Persistence ─────────────────────────────────────────────────

class TestPersistence:
    def test_record_creates_file(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        store.record("x.com", BrowserEngine.FIREFOX_CAMOUFOX)
        assert os.path.isfile(_json_path(store_dir))

    def test_file_round_trip(self, store_dir: str) -> None:
        s1 = EngineAffinityStore()
        s1.record("rt.com", BrowserEngine.FIREFOX_CAMOUFOX)

        s2 = EngineAffinityStore()
        assert s2.get("rt.com") is BrowserEngine.FIREFOX_CAMOUFOX

    def test_load_skips_expired_entries(self, store_dir: str) -> None:
        path = _json_path(store_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        expired_ts = time.time() - _TTL_SECONDS - 100
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"stale.com": [BrowserEngine.FIREFOX_CAMOUFOX.value, expired_ts]}, f)

        store = EngineAffinityStore()
        assert store.get("stale.com") is None

    def test_load_corrupt_json_starts_fresh(self, store_dir: str) -> None:
        path = _json_path(store_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{corrupt json!!")

        store = EngineAffinityStore()
        assert store.get("any.com") is None
        store.record("new.com", BrowserEngine.FIREFOX_CAMOUFOX)
        assert store.get("new.com") is BrowserEngine.FIREFOX_CAMOUFOX

    def test_load_malformed_entry_skipped(self, store_dir: str) -> None:
        path = _json_path(store_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "good.com": [BrowserEngine.FIREFOX_CAMOUFOX.value, time.time()],
                "bad.com": "not-a-list",
                "short.com": [BrowserEngine.FIREFOX_CAMOUFOX.value],
            }, f)

        store = EngineAffinityStore()
        assert store.get("good.com") is BrowserEngine.FIREFOX_CAMOUFOX
        assert store.get("bad.com") is None
        assert store.get("short.com") is None

    def test_flush_failure_does_not_raise(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        with patch("myrm_agent_harness.toolkits.browser.pool.engine_affinity._store_path", return_value="/dev/null/impossible/path"):
            store.record("fail.com", BrowserEngine.FIREFOX_CAMOUFOX)

    def test_clear_persists_to_disk(self, store_dir: str) -> None:
        s1 = EngineAffinityStore()
        s1.record("rm.com", BrowserEngine.FIREFOX_CAMOUFOX)
        s1.clear("rm.com")

        s2 = EngineAffinityStore()
        assert s2.get("rm.com") is None


# ── Invalid Engine Value ─────────────────────────────────────────────

class TestInvalidEngine:
    def test_invalid_engine_value_returns_none(self, store_dir: str) -> None:
        store = EngineAffinityStore()
        store._loaded = True
        store._cache["bad.com"] = ("nonexistent_engine", time.time())

        assert store.get("bad.com") is None
        assert "bad.com" not in store._cache


# ── Singleton ────────────────────────────────────────────────────────

class TestSingleton:
    def test_returns_same_instance(self, store_dir: str) -> None:
        a = get_engine_affinity_store()
        b = get_engine_affinity_store()
        assert a is b

    def test_singleton_is_functional(self, store_dir: str) -> None:
        store = get_engine_affinity_store()
        store.record("singleton.com", BrowserEngine.FIREFOX_CAMOUFOX)
        assert get_engine_affinity_store().get("singleton.com") is BrowserEngine.FIREFOX_CAMOUFOX
