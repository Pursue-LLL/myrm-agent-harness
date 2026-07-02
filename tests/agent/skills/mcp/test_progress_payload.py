"""Tests for shared notify/progress payload normalization."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.skills.mcp.progress_payload import (
    MAX_CATEGORY_LEN,
    MAX_DW_DISPLAY_MESSAGE,
    NotifyError,
    build_ptc_notify_payload,
    build_workflow_stage_event,
    parse_ptc_notify_params,
)


def test_parse_ptc_minimal_message() -> None:
    fields = parse_ptc_notify_params({"message": "hello"})
    assert fields.message == "hello"
    assert fields.level == "info"
    assert fields.progress is None
    assert fields.category is None


def test_build_ptc_payload_omits_unset_optional_fields() -> None:
    fields = parse_ptc_notify_params({"message": "hello", "level": "warn"})
    payload = build_ptc_notify_payload(fields, session_id="s1", trace_id="t1")
    assert payload["level"] == "warn"
    assert "progress" not in payload
    assert "category" not in payload


def test_build_workflow_stage_event_matches_dw_shape() -> None:
    event = build_workflow_stage_event(
        "msg-1",
        "Phase 1",
        progress=42,
        step_index=2,
        total_steps=5,
        category="analysis",
        level="info",
    )
    assert event["step_key"] == "workflow_stage"
    assert event["messageId"] == "msg-1"
    data = event["data"]
    assert data["message"] == "Phase 1"
    assert data["notify_progress"] == 42
    assert data["notify_category"] == "analysis"


def test_dw_category_truncated_to_ssot_max() -> None:
    event = build_workflow_stage_event("msg-1", "x", category="c" * 200)
    assert len(event["data"]["notify_category"]) == MAX_CATEGORY_LEN


def test_dw_message_truncated() -> None:
    event = build_workflow_stage_event("msg-1", "m" * (MAX_DW_DISPLAY_MESSAGE + 50))
    assert len(event["data"]["message"]) == MAX_DW_DISPLAY_MESSAGE


@pytest.mark.parametrize(
    "bad_params",
    [
        {"message": "x", "category": "x" * (MAX_CATEGORY_LEN + 1)},
        {"message": "x", "level": "panic"},
    ],
)
def test_parse_ptc_rejects_invalid(bad_params: dict[str, object]) -> None:
    with pytest.raises(NotifyError):
        parse_ptc_notify_params(bad_params)
