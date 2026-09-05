"""Unit tests for Salient Tool Output Filter & Verbatim Evidence Extractor."""

import pytest
from langchain_core.messages import ToolMessage
from myrm_agent_harness.api import (
    SalientToolEvidence,
    SalientToolFilterConfig,
    extract_salient_tool_evidences,
    strip_ansi_sequences,
)


def test_strip_ansi_sequences() -> None:
    raw = "\x1b[31mError:\x1b[0m test failed with \x1b[1;33mexit code 1\x1b[0m\n\x1b[2K\rDone"
    clean = strip_ansi_sequences(raw)
    assert clean == "Error: test failed with exit code 1\nDone"


def test_extract_salient_tool_evidences_with_nonzero_exit_code() -> None:
    msg = ToolMessage(
        content="pytest tests/test_payment.py\nFAILED (failures=1)\nAssertionError: 404 != 200",
        tool_call_id="call_123",
        name="bash",
        additional_kwargs={"exit_code": 1, "command": "pytest tests/test_payment.py"},
    )
    evidences = extract_salient_tool_evidences([msg])
    assert len(evidences) == 1
    ev = evidences[0]
    assert ev.tool_name == "bash"
    assert ev.tool_call_id == "call_123"
    assert ev.exit_code == 1
    assert ev.is_error is True
    assert ev.command == "pytest tests/test_payment.py"
    assert "AssertionError" in ev.snippet
    assert ev.salience_score >= 3.0


def test_truncate_with_head_tail() -> None:
    long_content = "HEAD_START_" + ("x" * 3000) + "_TAIL_END"
    msg = ToolMessage(
        content=f"Error: {long_content}",
        tool_call_id="call_long",
        name="bash",
        status="error",
    )
    cfg = SalientToolFilterConfig(max_snippet_chars=2048, head_chars=200, tail_chars=200)
    evidences = extract_salient_tool_evidences([msg], config=cfg)
    assert len(evidences) == 1
    ev = evidences[0]
    assert ev.snippet.startswith("Error: HEAD_START_")
    assert ev.snippet.endswith("_TAIL_END")
    assert "[... truncated " in ev.snippet
    assert len(ev.snippet) < 600


def test_benign_output_filtered_out() -> None:
    benign_msg = ToolMessage(
        content="Successfully generated 10 items. All good.",
        tool_call_id="call_benign",
        name="calculator",
    )
    evidences = extract_salient_tool_evidences([benign_msg])
    assert len(evidences) == 0


def test_dict_message_support() -> None:
    dict_msg = {
        "role": "tool",
        "content": "Traceback (most recent call last):\n  File 'app.py', line 10\nZeroDivisionError: division by zero",
        "metadata": {"tool_name": "python_execute", "tool_call_id": "py_456"},
    }
    evidences = extract_salient_tool_evidences([dict_msg])
    assert len(evidences) == 1
    assert evidences[0].tool_name == "python_execute"
    assert evidences[0].is_error is True
