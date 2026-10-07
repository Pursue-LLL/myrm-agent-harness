from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context import (
    HeuristicAnomalyKind,
    HistoricalRetrievalHeuristicTrigger,
    ToolExecutionFeedback,
)


@pytest.fixture
def trigger() -> HistoricalRetrievalHeuristicTrigger:
    return HistoricalRetrievalHeuristicTrigger(failure_threshold=2)


def test_success_resets_failure_count_and_does_not_trigger(
    trigger: HistoricalRetrievalHeuristicTrigger,
) -> None:
    # First failure
    f1 = trigger.record_tool_result(
        ToolExecutionFeedback(tool_name="read_file", success=False, error_message="temporary io lag")
    )
    assert f1.triggered is False
    assert trigger.consecutive_failures == 1

    # Followed by success
    s1 = trigger.record_tool_result(
        ToolExecutionFeedback(tool_name="read_file", success=True, error_message=None)
    )
    assert s1.triggered is False
    assert trigger.consecutive_failures == 0


def test_consecutive_failures_reach_threshold_and_trigger_hint(
    trigger: HistoricalRetrievalHeuristicTrigger,
) -> None:
    # 1st failure
    r1 = trigger.record_tool_result(
        ToolExecutionFeedback(tool_name="execute_sql", success=False, error_message="syntax error at position 12")
    )
    assert r1.triggered is False
    assert r1.system_hint_block is None

    # 2nd consecutive failure (threshold = 2 reached)
    r2 = trigger.record_tool_result(
        ToolExecutionFeedback(
            tool_name="execute_sql",
            success=False,
            error_message="column 'user_status' not found in table 'accounts'",
        )
    )
    assert r2.triggered is True
    assert r2.consecutive_failures == 2
    assert r2.system_hint_block is not None
    assert "<system_heuristic_retrieval_hint" in r2.system_hint_block
    assert "search_session_archive" in r2.system_hint_block
    assert "execute_sql" in r2.suggested_query_terms


def test_auth_or_config_anomaly_triggers_immediately(
    trigger: HistoricalRetrievalHeuristicTrigger,
) -> None:
    # Even on the first failure, missing API key / auth error must trigger immediately
    res = trigger.record_tool_result(
        ToolExecutionFeedback(
            tool_name="http_fetch",
            success=False,
            error_message="HTTP 401 Unauthorized: missing 'OPENAI_API_KEY' credentials",
        )
    )
    assert res.triggered is True
    assert res.matched_anomaly_kind == HeuristicAnomalyKind.AUTH_CREDENTIAL_MISSING
    assert res.system_hint_block is not None
    assert any("OPENAI_API_KEY" in t for t in res.suggested_query_terms)


def test_config_not_found_triggers_immediately(
    trigger: HistoricalRetrievalHeuristicTrigger,
) -> None:
    res = trigger.record_tool_result(
        ToolExecutionFeedback(
            tool_name="load_settings",
            success=False,
            error_message="Configuration file 'database_cluster.yaml' not found",
        )
    )
    assert res.triggered is True
    assert res.matched_anomaly_kind == HeuristicAnomalyKind.CONFIG_NOT_FOUND
    assert any("database_cluster.yaml" in t for t in res.suggested_query_terms)


def test_reset_clears_counter(trigger: HistoricalRetrievalHeuristicTrigger) -> None:
    trigger.record_tool_result(
        ToolExecutionFeedback(tool_name="probe", success=False, error_message="unknown probe failure")
    )
    assert trigger.consecutive_failures == 1
    trigger.reset()
    assert trigger.consecutive_failures == 0
