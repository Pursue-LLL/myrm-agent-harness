# [POS]: tests/unit/toolkits/memory/test_failure_historical_retrieval_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory.failure_retrieval
# [OUTPUT]: Unit test suite for FailureTriggeredHistoricalSessionRetrievalSuite (Item 109)

"""Unit tests for failure-triggered historical session retrieval suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.failure_retrieval import (
    ErrorFingerprintExtractor,
    FailureHistoricalSessionSearchEngine,
    FailureOutcomeType,
    FailureTriggerConfig,
    FailureTriggerInterceptor,
    HistoricalResolutionEntry,
)


@pytest.fixture
def extractor() -> ErrorFingerprintExtractor:
    return ErrorFingerprintExtractor()


@pytest.fixture
def search_engine() -> FailureHistoricalSessionSearchEngine:
    return FailureHistoricalSessionSearchEngine()


@pytest.fixture
def interceptor(search_engine: FailureHistoricalSessionSearchEngine) -> FailureTriggerInterceptor:
    return FailureTriggerInterceptor(search_engine=search_engine)


def test_error_fingerprint_scrubbing(extractor: ErrorFingerprintExtractor) -> None:
    """Verify volatile tokens like UUIDs, timestamps, addresses, and paths are scrubbed."""
    raw = (
        "ConnectionRefusedError: Failed to connect to 127.0.0.1:8000 at 2026-10-08T06:14:00Z "
        "socket 0x7ffee23b task-id e7f8a9b0-1234-5678-9abc-def012345678 "
        "tempfile /tmp/scratch_123.log"
    )
    fp = extractor.extract(raw, tool_name="network_fetch")
    assert fp.error_type == "ConnectionRefusedError"
    assert "<UUID>" in fp.normalized_pattern
    assert "<ADDR>" in fp.normalized_pattern
    assert "<TIME>" in fp.normalized_pattern
    assert "<TMP_PATH>" in fp.normalized_pattern
    assert "network" in fp.context_tags


def test_search_engine_seeded_dual_track_retrieval(
    search_engine: FailureHistoricalSessionSearchEngine,
    extractor: ErrorFingerprintExtractor,
) -> None:
    """Verify dual-track matching returns both successful fixes and cautionary dead ends."""
    raw_error = "PortAlreadyInUseError: bind address already in use on port 8000"
    fp = extractor.extract(raw_error, tool_name="run_command")

    result = search_engine.search(fp, top_n=2, include_cautionary=True)
    assert result.total_matched >= 2
    assert len(result.successful_resolutions) >= 1
    assert len(result.cautionary_failures) >= 1

    # Check successful resolution
    succ = result.successful_resolutions[0]
    assert succ.outcome_type == FailureOutcomeType.SUCCESSFUL_RESOLUTION
    assert "lsof" in succ.solution_snippet or "kill" in succ.solution_snippet

    # Check cautionary failure (warning against sleep retry loop)
    fail = result.cautionary_failures[0]
    assert fail.outcome_type == FailureOutcomeType.CAUTIONARY_FAILURE
    assert "sleep" in fail.solution_snippet


def test_direct_session_resolution_read(
    search_engine: FailureHistoricalSessionSearchEngine,
) -> None:
    """Verify direct one-click reading of historical session solution without guessing."""
    entry = search_engine.read_session_resolution("sess_git_reject_20260901", turn_index=4)
    assert entry is not None
    assert entry.session_id == "sess_git_reject_20260901"
    assert entry.outcome_type == FailureOutcomeType.SUCCESSFUL_RESOLUTION
    assert "git checkout -b" in entry.solution_snippet

    # Non-existent session returns None
    missing = search_engine.read_session_resolution("sess_non_existent")
    assert missing is None


def test_custom_resolution_indexing_and_retrieval(
    search_engine: FailureHistoricalSessionSearchEngine,
    extractor: ErrorFingerprintExtractor,
) -> None:
    """Verify dynamically indexing a new failure resolution and retrieving it."""
    custom_entry = HistoricalResolutionEntry(
        entry_id="hist_custom_oom_01",
        session_id="sess_oom_fix_20261001",
        turn_index=8,
        error_signature="MemoryLimitExceeded worker killed by OOM killer heap limit",
        outcome_type=FailureOutcomeType.SUCCESSFUL_RESOLUTION,
        solution_snippet="export NODE_OPTIONS=--max-old-space-size=4096",
        explanation="增大 Node.js V8 堆内存上限解决大矩阵解析 OOM 崩溃。",
    )
    search_engine.index_resolution(custom_entry)

    fp = extractor.extract("MemoryLimitExceeded worker killed by OOM killer heap limit")
    res = search_engine.search(fp)
    assert any(e.entry_id == "hist_custom_oom_01" for e in res.successful_resolutions)


def test_failure_trigger_interceptor_automation(
    interceptor: FailureTriggerInterceptor,
) -> None:
    """Verify non-invasive interceptor automatically triggers resolution retrieval on failure."""
    raw_error = "PermissionDeniedError git push rejected by pre-receive hook branch protected"
    result = interceptor.on_execution_failure(raw_error=raw_error, tool_name="run_command", exit_code=1)

    assert result is not None
    assert result.total_matched >= 1
    assert len(result.successful_resolutions) >= 1

    # Check formatted guidance block
    guidance = interceptor.format_resolution_guidance(result)
    assert "[FAILURE SELF-HEALING ADVICE" in guidance
    assert "git checkout -b" in guidance


def test_interceptor_disabled_skips_processing(
    search_engine: FailureHistoricalSessionSearchEngine,
) -> None:
    """Verify interceptor cleanly skips when disabled via config."""
    cfg = FailureTriggerConfig(enabled=False)
    interceptor = FailureTriggerInterceptor(search_engine=search_engine, config=cfg)

    result = interceptor.on_execution_failure("SomeError: connection refused")
    assert result is None
