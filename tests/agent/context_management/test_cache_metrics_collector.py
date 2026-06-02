"""Unit tests for cache_metrics_collector (NDJSON persistence + ContextVar pairing)."""

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from myrm_agent_harness.agent.context_management.infra.cache_metrics_collector import (
    PendingExplicitCacheSnapshot,
    clear_cache_usage_feedback,
    clear_pending_explicit_cache_snapshot,
    get_cache_usage_feedback,
    get_pending_cache_break_event,
    set_pending_explicit_cache_snapshot,
    take_pending_explicit_cache_snapshot,
    try_persist_cache_call_metrics,
)


@pytest.fixture
def metrics_dir(tmp_path: Path) -> Generator[Path]:
    from myrm_agent_harness.agent.context_management.infra.cache_metrics_collector import set_cache_metrics_dir

    d = tmp_path / "metrics"
    set_cache_metrics_dir(str(d))
    yield d
    set_cache_metrics_dir(None)


def test_pending_roundtrip_and_clear() -> None:
    clear_pending_explicit_cache_snapshot()
    snap = PendingExplicitCacheSnapshot(
        turn_count=3,
        breakpoint_count=2,
        message_count=10,
        total_estimated_tokens=8000,
        expected_cacheable_tokens=7000,
        compression_count=1,
    )
    set_pending_explicit_cache_snapshot(snap)
    taken = take_pending_explicit_cache_snapshot()
    assert taken == snap
    assert take_pending_explicit_cache_snapshot() is None


def test_persist_without_env_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYRM_CACHE_METRICS_DIR", raising=False)
    clear_cache_usage_feedback()
    clear_pending_explicit_cache_snapshot()
    try_persist_cache_call_metrics(
        {
            "model": "x",
            "usage": {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 50}},
        }
    )
    assert not list(tmp_path.iterdir())
    feedback = get_cache_usage_feedback()
    assert feedback is not None
    assert feedback.calls == 1
    assert feedback.input_tokens == 100
    assert feedback.cached_tokens == 50
    assert feedback.cache_hit_rate == pytest.approx(0.5)


def test_cache_usage_feedback_accumulates_without_metrics_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MYRM_CACHE_METRICS_DIR", raising=False)
    clear_cache_usage_feedback()

    try_persist_cache_call_metrics(
        {
            "model": "x",
            "usage": {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 20}},
        }
    )
    try_persist_cache_call_metrics(
        {
            "model": "x",
            "usage": {"prompt_tokens": 300, "prompt_tokens_details": {"cached_tokens": 180}},
        }
    )

    assert not list(tmp_path.iterdir())
    feedback = get_cache_usage_feedback()
    assert feedback is not None
    assert feedback.calls == 2
    assert feedback.input_tokens == 400
    assert feedback.cached_tokens == 200
    assert feedback.cache_hit_rate == pytest.approx(0.5)


def test_persist_writes_ndjson(metrics_dir: Path) -> None:
    clear_pending_explicit_cache_snapshot()
    snap = PendingExplicitCacheSnapshot(
        turn_count=2,
        breakpoint_count=1,
        message_count=4,
        total_estimated_tokens=500,
        expected_cacheable_tokens=400,
        compression_count=0,
    )
    set_pending_explicit_cache_snapshot(snap)
    try_persist_cache_call_metrics(
        {
            "model": "anthropic/claude-sonnet-4",
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 800},
            },
        }
    )
    files = list(metrics_dir.glob("cache_metrics_*.ndjson"))
    assert len(files) == 1
    line = files[0].read_text(encoding="utf-8").strip()
    row = json.loads(line)
    assert row["schema_version"] == 1
    assert row["explicit_cache_snapshot"] is True
    assert row["prompt_tokens"] == 1000
    assert row["completion_tokens"] == 10
    assert row["cached_tokens"] == 800
    assert row["actual_cache_hit_rate"] == pytest.approx(0.8)
    assert "total_tokens" not in row
    assert "explicit_cache" in row
    assert row["explicit_cache"]["breakpoint_count"] == 1
    assert "breakpoint_positions" not in row["explicit_cache"]
    assert "model_name" not in row["explicit_cache"]
    assert "chat_id" not in row["explicit_cache"]
    assert "safe_block_interval" not in row["explicit_cache"]


def test_invalid_usage_fields_raise_type_error(metrics_dir: Path) -> None:
    """Invalid types (str) raise TypeError and skip metrics collection."""
    clear_pending_explicit_cache_snapshot()
    with pytest.raises(TypeError, match="Expected int \\| float \\| None"):
        try_persist_cache_call_metrics(
            {
                "model": "m",
                "usage": {
                    "prompt_tokens": "not-a-number",
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            }
        )
    assert not list(metrics_dir.glob("cache_metrics_*.ndjson"))


def test_persist_consumes_pending(metrics_dir: Path) -> None:
    clear_pending_explicit_cache_snapshot()
    set_pending_explicit_cache_snapshot(
        PendingExplicitCacheSnapshot(
            turn_count=1,
            breakpoint_count=0,
            message_count=1,
            total_estimated_tokens=10,
            expected_cacheable_tokens=0,
            compression_count=0,
        )
    )
    try_persist_cache_call_metrics({"model": "m", "usage": {}})
    try_persist_cache_call_metrics({"model": "m", "usage": {}})
    files = list(metrics_dir.glob("cache_metrics_*.ndjson"))
    assert files[0].read_text(encoding="utf-8").count("\n") == 2
    lines = files[0].read_text(encoding="utf-8").strip().split("\n")
    second = json.loads(lines[1])
    assert second["explicit_cache_snapshot"] is False


def test_get_pending_cache_break_event_returns_none_without_break() -> None:
    """get_pending_cache_break_event returns None when no prior break stored."""
    # Drain any residue from earlier tests sharing the same ContextVar
    get_pending_cache_break_event()
    assert get_pending_cache_break_event() is None


def test_get_pending_cache_break_event_stores_break_info() -> None:
    """Cache break info is stored in ContextVar for SSE dispatch, even without NDJSON."""
    from myrm_agent_harness.agent.context_management.infra.cache_break_detector import (
        init_cache_break_detector,
        reset_cache_break_detector,
    )

    detector = init_cache_break_detector()
    try:
        # First call: establish baseline
        detector.check_cache_break(50_000, 0)
        try_persist_cache_call_metrics({
            "model": "m",
            "usage": {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 50000}},
        })
        # Consume any event from first call
        get_pending_cache_break_event()

        # Simulate a massive cache drop (50k -> 0)
        detector.record_prompt_state([], "m")
        try_persist_cache_call_metrics({
            "model": "m",
            "usage": {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 0}},
        })

        event = get_pending_cache_break_event()
        assert event is not None
        assert event["prev_cache_read"] == 50_000
        assert event["curr_cache_read"] == 0
        assert event["token_drop"] == 50_000
        assert isinstance(event["reasons"], list)

        # Second call should return None (consumed)
        assert get_pending_cache_break_event() is None
    finally:
        reset_cache_break_detector()
