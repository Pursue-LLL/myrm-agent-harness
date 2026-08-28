"""Unit tests for Task Friction Telemetry Pipeline (AgentTaskFrictionTelemetryPipeline)."""

import pytest

from myrm_agent_harness.observability.friction import (
    FrictionAggregator,
    FrictionCategory,
    FrictionExtractor,
    TaskFrictionEvent,
    friction_to_eval_case,
)


def test_friction_extractor_classification_and_from_error():
    """Test deterministic classification and event construction."""
    # 1. Format error classification
    cat1 = FrictionExtractor.classify_error_message("Invalid JSON schema: expected object, got string")
    assert cat1 == FrictionCategory.FORMAT_ERROR

    # 2. Timeout classification
    cat2 = FrictionExtractor.classify_error_message("Execution timed out after 30 seconds")
    assert cat2 == FrictionCategory.TOOL_TIMEOUT

    # 3. Permission denied
    cat3 = FrictionExtractor.classify_error_message("Access denied: permission blocked by sandbox")
    assert cat3 == FrictionCategory.PERMISSION_DENIED

    # 4. Spill overflow
    cat4 = FrictionExtractor.classify_error_message("Output buffer truncated: max tokens exceeded")
    assert cat4 == FrictionCategory.SPILL_OVERFLOW

    # 5. Construct from tool error
    event = FrictionExtractor.from_tool_error(
        session_id="sess_123",
        tool_name="bash_exec",
        error_message="Command failed with permission error",
        trace_id="trace_abc",
        input_payload={"cmd": "cat /etc/shadow"},
    )
    assert event.category == FrictionCategory.PERMISSION_DENIED
    assert event.session_id == "sess_123"
    assert event.tool_name == "bash_exec"
    assert event.trace_id == "trace_abc"
    assert event.input_payload is not None
    assert "/etc/shadow" in event.input_payload


def test_friction_extractor_from_event_stream():
    """Test extraction of friction points from raw event stream."""
    events = [
        {"event_type": "tool_start", "tool_name": "web_search"},
        {"event_type": "tool_end", "tool_name": "web_search", "status": "success"},
        {
            "event_type": "tool_failure",
            "tool_name": "python_repl",
            "error": "SyntaxError: invalid syntax during parse",
            "fault_side": "MODEL",
            "_trace_id": "trace_stream_99",
        },
    ]

    frictions = FrictionExtractor.extract_from_event_stream(
        events,
        session_id="sess_stream",
    )
    assert len(frictions) == 1
    assert frictions[0].category == FrictionCategory.FORMAT_ERROR
    assert frictions[0].tool_name == "python_repl"
    assert frictions[0].trace_id == "trace_stream_99"


def test_friction_aggregator_analytics():
    """Test statistical aggregation of friction points."""
    aggregator = FrictionAggregator()

    e1 = TaskFrictionEvent(
        category=FrictionCategory.FORMAT_ERROR,
        session_id="sess_a",
        tool_name="tool_sql",
        message="SQL syntax error",
    )
    e2 = TaskFrictionEvent(
        category=FrictionCategory.FORMAT_ERROR,
        session_id="sess_a",
        tool_name="tool_sql",
        message="SQL syntax error 2",
    )
    e3 = TaskFrictionEvent(
        category=FrictionCategory.TOOL_TIMEOUT,
        session_id="sess_a",
        tool_name="tool_browser",
        message="Page load timeout",
    )
    e4 = TaskFrictionEvent(
        category=FrictionCategory.SPILL_OVERFLOW,
        session_id="sess_b",
        tool_name="tool_file",
        message="File too large",
    )

    aggregator.record_batch([e1, e2, e3, e4])
    assert aggregator.total_count == 4

    summary = aggregator.summarize()
    assert summary.total_frictions == 4
    assert summary.by_category[FrictionCategory.FORMAT_ERROR.value] == 2
    assert summary.by_category[FrictionCategory.TOOL_TIMEOUT.value] == 1
    assert summary.by_tool["tool_sql"] == 2
    assert summary.top_frequent_tools[0] == ("tool_sql", 2)
    assert "sess_a" in summary.high_friction_sessions


def test_friction_to_eval_case_bridge():
    """Test converting TaskFrictionEvent into standardized EvalCase."""
    friction = TaskFrictionEvent(
        category=FrictionCategory.FORMAT_ERROR,
        session_id="sess_eval_1",
        tool_name="json_formatter",
        message="JSON decode error: unterminated string",
        trace_id="trace_eval_99",
        fault_side="MODEL",
        input_payload='{"raw": "test',
    )

    eval_case = friction_to_eval_case(friction)
    assert "eval_fric_format_error_" in eval_case.metadata["case_id"]
    assert "json_formatter" in eval_case.metadata["name"]
    assert "friction_regression" in eval_case.metadata["tags"]
    assert "cat_format_error" in eval_case.metadata["tags"]
    assert len(eval_case.state_assertions) == 1
    assert eval_case.metadata["source_session_id"] == "sess_eval_1"
    assert eval_case.metadata["source_trace_id"] == "trace_eval_99"
