"""Tests for web corpus aging — LRU eviction and disk quota."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.web_corpus.aging import CorpusAgingPolicy, run_aging
from myrm_agent_harness.toolkits.web_corpus.store import WebCorpusStore


@pytest.fixture()
def store(tmp_path: Path) -> WebCorpusStore:
    s = WebCorpusStore(tmp_path)
    yield s
    s.close()


def test_aging_evicts_old_entries(store: WebCorpusStore) -> None:
    store.upsert(url="https://old.com", title="Old", snippet="old page")
    past = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    store._conn.execute(
        "UPDATE web_corpus_meta SET last_accessed = ?", (past,)
    )

    policy = CorpusAgingPolicy(max_age_days=30, max_disk_mb=500)
    evicted = run_aging(store, policy)
    assert evicted == 1
    assert store.get_stats().total_entries == 0


def test_aging_keeps_recent_entries(store: WebCorpusStore) -> None:
    store.upsert(url="https://fresh.com", title="Fresh", snippet="fresh page")

    policy = CorpusAgingPolicy(max_age_days=30, max_disk_mb=500)
    evicted = run_aging(store, policy)
    assert evicted == 0
    assert store.get_stats().total_entries == 1


def test_aging_disk_quota_eviction(store: WebCorpusStore) -> None:
    large_content = "x" * 1_000_000
    store.upsert(url="https://big.com", title="Big", snippet="big page", content=large_content)

    policy = CorpusAgingPolicy(max_age_days=365, max_disk_mb=0)
    evicted = run_aging(store, policy)
    assert evicted >= 1


def test_default_policy() -> None:
    policy = CorpusAgingPolicy()
    assert policy.max_age_days == 30
    assert policy.max_disk_mb == 500
