"""Unit tests for Rate Limit Source Split Suite in myrm_agent_harness.observability.rate_limit_split."""

from concurrent.futures import ThreadPoolExecutor

from myrm_agent_harness.observability.rate_limit_split import (
    DEFAULT_UNKNOWN_PROVIDER,
    RateLimitMetricsSnapshot,
    RateLimitSource,
    RateLimitSplitTracker,
)


def test_initial_state_seeded_buckets() -> None:
    """Verify that tracker initializes with pre-seeded zero buckets and invariant totals."""
    tracker = RateLimitSplitTracker()
    snapshot: RateLimitMetricsSnapshot = tracker.get_snapshot()

    assert snapshot.total_requests == 0
    assert snapshot.total_completed == 0
    assert snapshot.total_rate_limited == 0
    assert snapshot.total_failed == 0
    assert snapshot.totals_consistent is True

    # Pre-seeded sources must be present at 0 to avoid empty Prometheus vectors
    assert snapshot.rate_limited_by_source == {"myrm": 0, "upstream": 0}
    assert snapshot.failed_by_provider == {DEFAULT_UNKNOWN_PROVIDER: 0}
    assert len(snapshot.recent_rate_limit_events) == 0
    assert len(snapshot.recent_failure_events) == 0


def test_rate_limit_split_myrm_vs_upstream() -> None:
    """Verify that 429 events are split into myrm vs upstream while keeping unlabelled total invariant."""
    tracker = RateLimitSplitTracker()

    ev1 = tracker.record_rate_limit(
        source=RateLimitSource.MYRM,
        provider="openai",
        model="gpt-4o",
        reason="Local concurrent token budget reached",
    )
    assert ev1.source == RateLimitSource.MYRM
    assert ev1.provider == "openai"

    ev2 = tracker.record_rate_limit(
        source="upstream",
        provider="anthropic",
        model="claude-3-5-sonnet",
        reason="Provider HTTP 429 Too Many Requests",
    )
    assert ev2.source == RateLimitSource.UPSTREAM
    assert ev2.provider == "anthropic"

    # governor / internal aliases
    ev3 = tracker.record_rate_limit(
        source="governor",
        provider="deepseek",
        model="deepseek-chat",
    )
    assert ev3.source == RateLimitSource.MYRM

    snapshot = tracker.get_snapshot()
    assert snapshot.total_rate_limited == 3
    assert snapshot.total_requests == 3
    assert snapshot.rate_limited_by_source["myrm"] == 2
    assert snapshot.rate_limited_by_source["upstream"] == 1
    assert snapshot.totals_consistent is True
    assert len(snapshot.recent_rate_limit_events) == 3


def test_failed_attributed_by_provider() -> None:
    """Verify that request failures are attributed to provider while unlabelled total remains invariant."""
    tracker = RateLimitSplitTracker()

    tracker.record_failure(provider="openai", model="gpt-4o", error_code="CONTEXT_LENGTH_EXCEEDED")
    tracker.record_failure(provider="deepseek", model="deepseek-r1", error_code="UPSTREAM_500")
    tracker.record_failure(provider=None, error_code="TIMEOUT")

    snapshot = tracker.get_snapshot()
    assert snapshot.total_failed == 3
    assert snapshot.total_requests == 3
    assert snapshot.failed_by_provider["openai"] == 1
    assert snapshot.failed_by_provider["deepseek"] == 1
    assert snapshot.failed_by_provider[DEFAULT_UNKNOWN_PROVIDER] == 1
    assert len(snapshot.recent_failure_events) == 3


def test_completed_and_reset() -> None:
    """Verify request completion counting and reset semantics."""
    tracker = RateLimitSplitTracker()
    tracker.record_completed(provider="anthropic", model="claude-3-5-sonnet")
    tracker.record_rate_limit(source=RateLimitSource.MYRM)
    tracker.record_failure(provider="openai")

    snap1 = tracker.get_snapshot()
    assert snap1.total_requests == 3
    assert snap1.total_completed == 1
    assert snap1.total_rate_limited == 1
    assert snap1.total_failed == 1

    tracker.reset()
    snap2 = tracker.get_snapshot()
    assert snap2.total_requests == 0
    assert snap2.total_completed == 0
    assert snap2.total_rate_limited == 0
    assert snap2.total_failed == 0
    assert snap2.rate_limited_by_source == {"myrm": 0, "upstream": 0}
    assert snap2.failed_by_provider == {DEFAULT_UNKNOWN_PROVIDER: 0}


def test_concurrent_recording_thread_safety() -> None:
    """Verify thread-safety when recording under concurrent workers."""
    tracker = RateLimitSplitTracker(max_recent_events=50)

    def worker_task(index: int) -> None:
        if index % 3 == 0:
            tracker.record_rate_limit(RateLimitSource.MYRM, provider="openai")
        elif index % 3 == 1:
            tracker.record_rate_limit(RateLimitSource.UPSTREAM, provider="anthropic")
        else:
            tracker.record_failure(provider="deepseek", error_code="ERR_RATE")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker_task, range(90)))

    snapshot = tracker.get_snapshot()
    assert snapshot.total_requests == 90
    assert snapshot.total_rate_limited == 60
    assert snapshot.rate_limited_by_source["myrm"] == 30
    assert snapshot.rate_limited_by_source["upstream"] == 30
    assert snapshot.total_failed == 30
    assert snapshot.failed_by_provider["deepseek"] == 30
    assert snapshot.totals_consistent is True
